import { Children, isValidElement, memo, useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from './api'
import type { Artifact, DraftPolicy, Inspection, Job, KnowledgeFile, KnowledgeProfile, StageName, Status } from './types'

const stageLabels: Record<StageName, string> = {
  parse: '解析', acquire: '获取素材', transcribe: '转写', generate: '生成知识稿', organize: '归档知识', publish: '发布',
}

const statusLabels: Record<Status, string> = {
  pending: '等待', queued: '排队', running: '处理中', completed: '完成', failed: '失败',
  cancelled: '已取消', skipped: '已复用',
}

const NOTICE_DURATION_MS = 4500
const HEALTH_CHECK_INTERVAL_MS = 10_000
const HOME_JOB_LIMIT = 5

function duration(value?: number) {
  if (!value) return '—'
  const h = Math.floor(value / 3600)
  const m = Math.floor((value % 3600) / 60)
  const s = Math.floor(value % 60)
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '发生未知错误'
}

function hasKnowledgeOutput(job: Job) {
  const artifacts = [...job.artifacts, ...job.parts.flatMap(part => part.artifacts)]
  return artifacts.some(artifact => ['document', 'topic', 'index'].includes(artifact.kind))
}

function jobErrorAlreadyShownByStage(job: Job) {
  return Boolean(job.error && job.parts.some(part =>
    part.stages.some(stage => stage.error === job.error),
  ))
}

function retryableFailure(job: Job) {
  for (const part of job.parts) {
    const failedStage = part.stages.find(stage => stage.status === 'failed')
    if (failedStage && ['transcribe', 'generate', 'organize', 'publish'].includes(failedStage.stage)) {
      return { partId: part.id, stage: failedStage }
    }
  }
  return null
}

function fileSize(value: number | null) {
  if (value === null) return ''
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function KnowledgeTree({ entries, expanded, selectedPath, onToggle, onSelect }: {
  entries: KnowledgeFile[]
  expanded: Set<string>
  selectedPath?: string
  onToggle: (path: string) => void
  onSelect: (entry: KnowledgeFile) => void
}) {
  return <ul className="knowledge-tree">
    {entries.map(entry => <li key={entry.path}>
      <button
        className={`${entry.type} ${selectedPath === entry.path ? 'selected' : ''}`}
        onClick={() => entry.type === 'directory' ? onToggle(entry.path) : onSelect(entry)}
        title={entry.path}
      >
        <span className="tree-arrow">{entry.type === 'directory' ? (expanded.has(entry.path) ? '⌄' : '›') : ''}</span>
        <span className="tree-icon">{entry.type === 'directory' ? '▰' : entry.name.endsWith('.md') ? 'M↓' : '·'}</span>
        <span>{entry.name}</span>
        {entry.type === 'file' && <small>{fileSize(entry.size)}</small>}
      </button>
      {entry.type === 'directory' && expanded.has(entry.path) && entry.children && <KnowledgeTree
        entries={entry.children} expanded={expanded} selectedPath={selectedPath}
        onToggle={onToggle} onSelect={onSelect}
      />}
    </li>)}
  </ul>
}

const MarkdownView = memo(function MarkdownView({ content }: { content: string }) {
  return <ReactMarkdown
    remarkPlugins={[remarkGfm]}
    components={{
      li({ children, ...props }) {
        const nodes = Children.toArray(children)
        const nestedLists = nodes.filter(node => isValidElement(node) && node.type === 'ul')
        if (!nestedLists.length) return <li {...props}>{children}</li>
        const summary = nodes.filter(node => !nestedLists.includes(node))
        return <li {...props} className="collapsible-knowledge"><details><summary>{summary}</summary>{nestedLists}</details></li>
      },
    }}
  >{content}</ReactMarkdown>
})

export default function App() {
  const [url, setUrl] = useState('')
  const [inspection, setInspection] = useState<Inspection | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [settings, setSettings] = useState<Record<string, string | boolean | null>>({})
  const [profiles, setProfiles] = useState<KnowledgeProfile[]>([])
  const [jobProfileId, setJobProfileId] = useState('')
  const [draftPolicy, setDraftPolicy] = useState<DraftPolicy>('reuse')
  const [knowledgeProfileId, setKnowledgeProfileId] = useState('')
  const [profileDraft, setProfileDraft] = useState<KnowledgeProfile | null>(null)
  const [profileOpen, setProfileOpen] = useState(false)
  const [profileTab, setProfileTab] = useState<'editor' | 'guide'>('editor')
  const [busy, setBusy] = useState(false)
  const [deletingJobId, setDeletingJobId] = useState<string | null>(null)
  const [retryingFailedJobs, setRetryingFailedJobs] = useState(false)
  const [regeneratingKnowledge, setRegeneratingKnowledge] = useState(false)
  const [regenerateConfirmOpen, setRegenerateConfirmOpen] = useState(false)
  const [notice, setNotice] = useState('')
  const [preview, setPreview] = useState<{ title: string; content: string; id: string; kind: 'document' | 'transcript' } | null>(null)
  const [knowledgeOpen, setKnowledgeOpen] = useState(false)
  const [knowledgeFiles, setKnowledgeFiles] = useState<KnowledgeFile[]>([])
  const [knowledgeLoading, setKnowledgeLoading] = useState(false)
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set())
  const [knowledgeSelection, setKnowledgeSelection] = useState<{ entry: KnowledgeFile; content?: string } | null>(null)
  const [refactoringPath, setRefactoringPath] = useState<string | null>(null)
  const [refactorConfirmOpen, setRefactorConfirmOpen] = useState(false)
  const [serviceStatus, setServiceStatus] = useState<'connecting' | 'running' | 'worker-stopped' | 'disconnected'>('connecting')
  const [page, setPage] = useState<'home' | 'history'>('home')
  const [historyQuery, setHistoryQuery] = useState('')
  const [historyProfileId, setHistoryProfileId] = useState('all')
  const [historyStatus, setHistoryStatus] = useState<'all' | 'active' | 'completed' | 'failed'>('all')
  const [expandedHistoryJobId, setExpandedHistoryJobId] = useState<string | null>(null)

  const active = useMemo(() => jobs.some(job => ['queued', 'running'].includes(job.status)), [jobs])
  const activeProfile = useMemo(
    () => profiles.find(profile => profile.is_active),
    [profiles],
  )
  const activeProfileJobs = useMemo(
    () => jobs.filter(job => job.profile_id === activeProfile?.id),
    [activeProfile?.id, jobs],
  )
  const activeProfileBusy = useMemo(
    () => activeProfileJobs.some(job => ['queued', 'running'].includes(job.status)),
    [activeProfileJobs],
  )
  const retryableFailedJobs = useMemo(() => jobs.flatMap(job => {
    if (job.profile_id !== activeProfile?.id || job.status !== 'failed') return []
    const target = retryableFailure(job)
    return target ? [{ job, target }] : []
  }), [activeProfile?.id, jobs])
  const visibleJobs = useMemo(() => {
    const orderedJobs = [...jobs].sort((left, right) => {
      const runningDifference = Number(right.status === 'running') - Number(left.status === 'running')
      if (runningDifference) return runningDifference
      return Date.parse(right.updated_at || right.created_at) - Date.parse(left.updated_at || left.created_at)
    })
    if (page === 'home') return orderedJobs.slice(0, HOME_JOB_LIMIT)
    const query = historyQuery.trim().toLocaleLowerCase()
    const statusMatches = (status: Status) => historyStatus === 'all'
      || (historyStatus === 'active' && ['pending', 'queued', 'running'].includes(status))
      || (historyStatus === 'completed' && ['completed', 'skipped'].includes(status))
      || (historyStatus === 'failed' && ['failed', 'cancelled'].includes(status))
    return orderedJobs.filter(job =>
      statusMatches(job.status)
      && (historyProfileId === 'all' || job.profile_id === historyProfileId)
      && (!query || `${job.video_title} ${job.bvid} ${job.video_url || ''} ${job.profile_name || ''}`.toLocaleLowerCase().includes(query)),
    )
  }, [historyProfileId, historyQuery, historyStatus, jobs, page])

  const refresh = async () => {
    try { setJobs(await api.jobs()) } catch (error) { setNotice(errorText(error)) }
  }

  const loadProfiles = async (preferredId?: string) => {
    const result = await api.profiles()
    setProfiles(result)
    const selected = result.find(profile => profile.id === preferredId)
      || result.find(profile => profile.is_active)
      || result[0]
    setJobProfileId(current => result.some(profile => profile.id === current)
      ? current
      : (selected?.id || ''))
    setProfileDraft(selected ? JSON.parse(JSON.stringify(selected)) as KnowledgeProfile : null)
  }

  useEffect(() => {
    void refresh()
    api.settings().then(setSettings).catch(error => setNotice(errorText(error)))
    loadProfiles().catch(error => setNotice(errorText(error)))
  }, [])

  useEffect(() => {
    let active = true
    const checkHealth = async () => {
      try {
        const health = await api.health()
        if (active) setServiceStatus(health.ok && health.worker === 'running' ? 'running' : 'worker-stopped')
      } catch {
        if (active) setServiceStatus('disconnected')
      }
    }
    void checkHealth()
    const timer = window.setInterval(() => void checkHealth(), HEALTH_CHECK_INTERVAL_MS)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => void refresh(), 2000)
    return () => window.clearInterval(timer)
  }, [active])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), NOTICE_DURATION_MS)
    return () => window.clearTimeout(timer)
  }, [notice])

  async function inspect() {
    if (!url.trim()) return
    setBusy(true); setNotice('')
    try {
      const result = await api.inspect(url.trim())
      setInspection(result)
    } catch (error) { setNotice(errorText(error)) }
    finally { setBusy(false) }
  }

  async function submit() {
    if (!inspection?.parts[0] || !jobProfileId) return
    setBusy(true); setNotice('')
    try {
      await api.createJob(inspection.id, [inspection.parts[0].id], jobProfileId, draftPolicy)
      setInspection(null); setUrl('')
      await refresh()
      setNotice('任务已加入本地队列')
    } catch (error) { setNotice(errorText(error)) }
    finally { setBusy(false) }
  }

  async function showDocument(id: string, title: string) {
    try { setPreview({ id, title, content: await api.document(id), kind: 'document' }) }
    catch (error) { setNotice(errorText(error)) }
  }

  async function showTopics(topics: Artifact[], update: Artifact | undefined, partTitle: string) {
    try {
      if (update) {
        try {
          const raw = await api.document(update.id)
          const payload = JSON.parse(raw) as {
            plans?: Array<{
              action?: string
              target_path?: string
              title?: string
              sections?: { knowledge?: string[]; disagreements?: string[] }
            }>
          }
          const plans = (payload.plans || []).filter(plan => plan.action === 'create' || plan.action === 'merge')
          const lines: string[] = ['# 本次归档新增', '', `> 只展示本次写入主题的新增内容，便于核对；主题里已有的内容请在“浏览知识库”查看。`, '']
          if (!plans.length) {
            lines.push('本次没有新增或更新的主题知识。', '')
          }
          plans.forEach((plan, index) => {
            const actionLabel = plan.action === 'create' ? '新建' : '合并'
            const path = plan.target_path || '未命名主题'
            const name = plan.title || path.split(/[\\/]/).pop()?.replace(/\.md$/, '') || '未命名主题'
            const knowledge = plan.sections?.knowledge || []
            const disagreements = plan.sections?.disagreements || []
            lines.push(`## ${index + 1}. ${actionLabel}「${name}」`, '', `\`${path}\``, '')
            if (!knowledge.length && !disagreements.length) {
              lines.push('本次没有实质新增。', '')
            }
            knowledge.forEach(item => lines.push(`- ${item}`))
            if (disagreements.length) {
              lines.push('', '**不同观点与争议**', '')
              disagreements.forEach(item => lines.push(`- ${item}`))
            }
            lines.push('')
          })
          setPreview({
            id: update.id,
            title: `${partTitle} · 本次归档新增`,
            content: lines.join('\n'),
            kind: 'document',
          })
          return
        } catch {
          // 归档记录缺失或无法解析时，退回展示主题全文
        }
      }
      const documents = await Promise.all(topics.map(async topic => ({
        topic,
        content: await api.document(topic.id),
      })))
      const content = documents.map(({ topic, content: raw }) => {
        const name = topic.path.split(/[\\/]/).pop()?.replace(/\.md$/, '') || '未命名主题'
        const body = raw
          .replace(/^---\s*\n[\s\S]*?\n---\s*\n+/, '')
          .replace(/^#\s+[^\n]+\n+/, '')
          .trim()
        return `# ${name}\n\n${body}`
      }).join('\n\n---\n\n')
      setPreview({
        id: topics[0]?.id || '',
        title: `${partTitle} · ${topics.length} 个归档主题`,
        content,
        kind: 'document',
      })
    } catch (error) { setNotice(errorText(error)) }
  }

  async function showTranscript(id: string, title: string) {
    try {
      const segments = await api.transcript(id)
      const stamp = (seconds: number) => {
        const total = Math.max(0, Math.floor(seconds))
        const hours = Math.floor(total / 3600)
        const minutes = Math.floor((total % 3600) / 60)
        const secs = total % 60
        return hours
          ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
          : `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
      }
      const content = [
        '# 转写中间结果', '',
        `共 ${segments.length} 个片段；来源：${segments[0]?.source === 'subtitle' ? '公开视频字幕' : '语音转写'}`, '',
        ...segments.map(segment => `- **${stamp(segment.start)}–${stamp(segment.end)}** ${segment.text}`),
      ].join('\n')
      setPreview({ id, title: `${title} · 转写`, content, kind: 'transcript' })
    } catch (error) { setNotice(errorText(error)) }
  }

  async function openKnowledge() {
    const profileId = profiles.find(profile => profile.is_active)?.id || profiles[0]?.id || ''
    setKnowledgeProfileId(profileId)
    setKnowledgeOpen(true)
    setKnowledgeLoading(true)
    try {
      const files = await api.knowledgeFiles(profileId)
      setKnowledgeFiles(files)
      setKnowledgeSelection(null)
      setExpandedPaths(new Set(files.map(item => item.path)))
    } catch (error) { setNotice(errorText(error)) }
    finally { setKnowledgeLoading(false) }
  }

  async function selectKnowledgeFile(entry: KnowledgeFile) {
    setKnowledgeSelection({ entry })
    if (!entry.previewable) return
    try { setKnowledgeSelection({ entry, content: await api.knowledgeFile(entry.path, knowledgeProfileId) }) }
    catch (error) { setNotice(errorText(error)) }
  }

  async function switchKnowledgeProfile(profileId: string) {
    setKnowledgeProfileId(profileId)
    setKnowledgeLoading(true)
    setKnowledgeSelection(null)
    try {
      const files = await api.knowledgeFiles(profileId)
      setKnowledgeFiles(files)
      setExpandedPaths(new Set(files.map(item => item.path)))
    } catch (error) { setNotice(errorText(error)) }
    finally { setKnowledgeLoading(false) }
  }

  function toggleKnowledgeDirectory(path: string) {
    setExpandedPaths(current => {
      const next = new Set(current)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  async function refactorKnowledgeFile() {
    const entry = knowledgeSelection?.entry
    if (!entry || refactoringPath) return
    setRefactorConfirmOpen(false)
    setRefactoringPath(entry.path)
    try {
      const content = await api.refactorKnowledgeFile(entry.path, knowledgeProfileId)
      setKnowledgeSelection({ entry, content })
      setNotice('已整理合并')
      const files = await api.knowledgeFiles(knowledgeProfileId)
      setKnowledgeFiles(files)
    } catch (error) { setNotice(errorText(error)) }
    finally { setRefactoringPath(null) }
  }

  async function deleteFinishedJob(job: Job) {
    if (deletingJobId) return
    const statusLabel = job.status === 'cancelled' ? '已取消' : '失败'
    if (!window.confirm(`确定删除这条${statusLabel}任务吗？任务记录和中间文件将被清理。`)) return
    setDeletingJobId(job.id)
    try {
      await api.deleteJob(job.id)
      await refresh()
      setNotice(`${statusLabel}任务已删除；该任务未生成知识文档`)
    } catch (error) { setNotice(errorText(error)) }
    finally { setDeletingJobId(null) }
  }

  async function retryOrganize(jobId: string, partId: string) {
    try {
      await api.retry(jobId, partId, 'organize')
      await refresh()
      setNotice('已重新加入归档队列；不会重复转写或生成知识正文')
    } catch (error) { setNotice(errorText(error)) }
  }

  async function retryAllFailedJobs() {
    if (retryingFailedJobs || !retryableFailedJobs.length) return
    setRetryingFailedJobs(true)
    let succeeded = 0
    const errors: string[] = []
    for (const { job, target } of retryableFailedJobs) {
      try {
        await api.retry(job.id, target.partId, target.stage.stage)
        succeeded += 1
      } catch (error) { errors.push(`${job.bvid}：${errorText(error)}`) }
    }
    await refresh()
    setNotice(errors.length
      ? `批量重试完成：成功 ${succeeded} 条，失败 ${errors.length} 条；${errors[0]}`
      : `已将 ${succeeded} 条失败任务从各自失败阶段重新加入队列`)
    setRetryingFailedJobs(false)
  }

  async function regenerateKnowledgeBase() {
    if (regeneratingKnowledge || activeProfileBusy || !activeProfile) return
    setRegenerateConfirmOpen(false)
    setRegeneratingKnowledge(true)
    try {
      const result = await api.regenerateKnowledge(activeProfile.id)
      await refresh()
      setNotice(`已清空当前知识库的旧归档并重新排队：${result.queued_jobs} 条任务`)
    } catch (error) { setNotice(errorText(error)) }
    finally { setRegeneratingKnowledge(false) }
  }

  async function testConnection(service: 'stt' | 'llm') {
    setNotice(`正在测试 ${service.toUpperCase()}…`)
    try { const result = await api.test(service); setNotice(`${service.toUpperCase()}：${result.message}`) }
    catch (error) { setNotice(errorText(error)) }
  }

  function selectProfile(id: string) {
    const selected = profiles.find(profile => profile.id === id)
    if (selected) setProfileDraft(JSON.parse(JSON.stringify(selected)) as KnowledgeProfile)
  }

  function newProfile() {
    setProfileDraft({
      id: '', name: '', mode: 'open', scope: '', preferred_topics: [],
      rules: { ignore_out_of_scope: false, merge_similar: true },
      is_active: false, version: 0, created_at: '', updated_at: '',
    })
  }

  async function saveProfile() {
    if (!profileDraft?.name.trim()) return
    setBusy(true); setNotice('')
    try {
      const saved = profileDraft.id
        ? await api.updateProfile(profileDraft)
        : await api.createProfile(profileDraft)
      await loadProfiles(saved.id)
      setProfileOpen(false)
      setNotice('知识库 Profile 已保存')
    } catch (error) { setNotice(errorText(error)) }
    finally { setBusy(false) }
  }

  async function activateProfile() {
    if (!profileDraft?.id) return
    try {
      await api.activateProfile(profileDraft.id)
      await loadProfiles(profileDraft.id)
      setNotice(`已启用「${profileDraft.name}」`)
    } catch (error) { setNotice(errorText(error)) }
  }

  async function deleteProfile() {
    if (!profileDraft?.id || profileDraft.is_active) return
    if (!window.confirm(`确定删除空知识库「${profileDraft.name}」吗？\n\n已有历史任务或知识内容的知识库不能删除。`)) return
    try {
      await api.deleteProfile(profileDraft.id)
      await loadProfiles()
      setNotice('Profile 已删除')
    } catch (error) { setNotice(errorText(error)) }
  }

  function updateTopic(index: number, key: 'name' | 'description', value: string) {
    setProfileDraft(current => current && ({
      ...current,
      preferred_topics: current.preferred_topics.map((topic, topicIndex) =>
        topicIndex === index ? { ...topic, [key]: value } : topic),
    }))
  }

  async function suggestTopic(index: number) {
    if (!profileDraft?.id) { setNotice('请先保存新 Profile，再使用 AI 路径建议'); return }
    const topic = profileDraft.preferred_topics[index]
    if (!topic.name.trim()) return
    try {
      const suggestion = await api.suggestTopic(profileDraft.id, topic.name, topic.description)
      if (suggestion.action === 'use_existing') {
        const existingName = profileDraft.preferred_topics.find(item => item.path === suggestion.path)?.name || '已有主题'
        setProfileDraft(current => current && ({
          ...current,
          preferred_topics: current.preferred_topics.filter((_, topicIndex) => topicIndex !== index),
        }))
        setNotice(`建议复用「${existingName}」：${suggestion.reason}`)
      } else {
        setProfileDraft(current => current && ({
          ...current,
          preferred_topics: current.preferred_topics.map((item, topicIndex) =>
            topicIndex === index ? { ...item, path: suggestion.path } : item),
        }))
        setNotice(`AI 已完成主题归类建议：${suggestion.reason}`)
      }
    } catch (error) { setNotice(errorText(error)) }
  }

  function exportProfile() {
    if (!profileDraft) return
    const content = JSON.stringify({
      name: profileDraft.name, mode: profileDraft.mode, scope: profileDraft.scope,
      preferred_topics: profileDraft.preferred_topics,
    }, null, 2)
    const link = document.createElement('a')
    link.href = URL.createObjectURL(new Blob([content], { type: 'application/json' }))
    link.download = `${profileDraft.name}.json`
    link.click()
    URL.revokeObjectURL(link.href)
  }

  return <>
    <header className={`hero ${page === 'history' ? 'history-hero' : ''}`}>
      <nav><button className="brand brand-button" onClick={() => setPage('home')}><img src="/favicon.svg" alt=""/>拾影成文</button><div className="nav-actions">{page === 'home' ? <><button onClick={() => setPage('history')}>历史任务</button><button onClick={() => void openKnowledge()}>浏览知识库</button><button onClick={() => { setProfileTab('editor'); setProfileOpen(true) }}>知识库设置</button></> : <button onClick={() => setPage('home')}>← 返回首页</button>}<span className={`local-pill ${serviceStatus}`} role="status">● {{ connecting: '连接中', running: '正常运行', 'worker-stopped': '队列已停止', disconnected: '服务断开' }[serviceStatus]}</span></div></nav>
      {page === 'home' && <div className="hero-copy"><p className="eyebrow">BILIBILI → KNOWLEDGE</p><h1>让视频的价值，<br/><em>沉淀为可引用的知识。</em></h1><p>字幕优先 · 自动转写 · AI 归纳 · Markdown 永久保存</p></div>}
    </header>

    <main className={page === 'history' ? 'history-main' : ''}>
      {notice && <div className="notice" role="status">{notice}<button aria-label="关闭提示" onClick={() => setNotice('')}>×</button></div>}

      {page === 'home' && <section className="card create-card">
        <div className="section-heading"><span>01</span><div><h2>开始一次整理</h2><p>粘贴单 P 的普通 BV 视频链接，解析后即可生成知识文档。</p></div></div>
        <div className="url-row">
          <input aria-label="Bilibili 视频链接" value={url} onChange={e => setUrl(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && void inspect()} placeholder="https://www.bilibili.com/video/BV…" />
          <button className="primary" disabled={busy || !url.trim()} onClick={() => void inspect()}>{busy ? '解析中…' : '解析视频'}</button>
        </div>

        {inspection && <div className="inspection">
          <div className="video-meta">
            {inspection.cover_url && <img src={inspection.cover_url} alt="视频封面" referrerPolicy="no-referrer" />}
            <div><span>{inspection.bvid}</span><h3>{inspection.title}</h3><p>{inspection.uploader || '未知 UP 主'} · {duration(inspection.duration)}</p></div>
          </div>
          <div className="job-options">
            <label><small>目标知识库</small><select aria-label="目标知识库" value={jobProfileId} onChange={event => setJobProfileId(event.target.value)}>{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
            <div><small>知识稿</small><div className="draft-policy" role="group" aria-label="知识稿生成方式"><button className={draftPolicy === 'reuse' ? 'selected' : ''} onClick={() => setDraftPolicy('reuse')}>复用已有</button><button className={draftPolicy === 'regenerate' ? 'selected' : ''} onClick={() => setDraftPolicy('regenerate')}>重新生成</button></div></div>
          </div>
          <button className="primary submit" disabled={busy || !inspection.parts.length || !jobProfileId} onClick={() => void submit()}>应用到知识库 →</button>
        </div>}
      </section>}

      {page === 'history' && <section className="history-page">
        <div className="history-heading"><div><small>ALL PROCESSING JOBS</small><h2>历史任务</h2><p>共 {jobs.length} 条解析记录</p></div><div className="history-heading-actions">{retryableFailedJobs.length > 0 && <button className="ghost quick-retry" disabled={retryingFailedJobs} onClick={() => void retryAllFailedJobs()}>{retryingFailedJobs ? '正在批量重试…' : `一键重试当前知识库失败任务（${retryableFailedJobs.length}）`}</button>}<button className="ghost danger history-regenerate" title={activeProfileBusy ? '请等待当前知识库的队列处理完成' : '保留知识稿，重新归档当前启用的知识库'} disabled={regeneratingKnowledge || activeProfileBusy || !activeProfileJobs.length} onClick={() => setRegenerateConfirmOpen(true)}>{regeneratingKnowledge ? '正在清空并排队…' : '重新归档当前知识库'}</button></div></div>
        <div className="history-tools"><label className="history-search"><span aria-hidden="true">⌕</span><input aria-label="搜索历史任务" value={historyQuery} onChange={event => setHistoryQuery(event.target.value)} placeholder="搜索标题、BV 号或知识库"/>{historyQuery && <button aria-label="清空搜索" onClick={() => setHistoryQuery('')}>×</button>}</label><label className="history-profile-filter"><small>知识库</small><select aria-label="筛选知识库" value={historyProfileId} onChange={event => setHistoryProfileId(event.target.value)}><option value="all">全部知识库</option>{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name}{profile.is_active ? '（当前）' : ''}</option>)}</select></label><div className="history-status-tabs" role="group" aria-label="筛选任务状态">{([['all', '全部'], ['active', '处理中'], ['completed', '已完成'], ['failed', '失败']] as const).map(([status, label]) => <button key={status} className={historyStatus === status ? 'active' : ''} onClick={() => setHistoryStatus(status)}>{label}</button>)}</div><button className="history-refresh" onClick={() => void refresh()}>↻ 刷新</button></div>
        <div className="history-summary">找到 {visibleJobs.length} 条记录</div>
      </section>}

      <section className={`tasks ${page === 'history' ? 'history-tasks' : ''}`}>
        {page === 'home' && <div className="section-heading"><span>02</span><div><h2>最近任务</h2><p>仅显示最近 {HOME_JOB_LIMIT} 条，完整记录请进入历史任务。</p></div><div className="heading-actions"><button className="ghost" onClick={() => void refresh()}>刷新</button>{jobs.length > HOME_JOB_LIMIT && <button className="ghost" onClick={() => setPage('history')}>查看全部 {jobs.length} 条</button>}</div></div>}
        {!visibleJobs.length && <div className="empty">{jobs.length ? '没有符合条件的历史任务。' : '还没有任务。提交第一个视频后，处理进度会显示在这里。'}</div>}
        {visibleJobs.map(job => {
          const historyExpanded = page === 'history' && expandedHistoryJobId === job.id
          const profileName = job.profile_name || profiles.find(profile => profile.id === job.profile_id)?.name || '未归属知识库'
          return <article className={`job-card ${page === 'history' ? 'history-job' : ''} ${historyExpanded ? 'expanded' : ''}`} key={job.id}>
          <div className="job-head"><div><div className="job-context"><span className="job-bvid">{job.bvid}</span><span className="job-profile">{profileName}</span></div><h3>{job.video_title}</h3><small>{page === 'history' ? '最后更新：' : ''}{new Date(page === 'history' ? (job.updated_at || job.created_at) : job.created_at).toLocaleString()}</small>{page === 'history' && job.video_url && <a className="history-source-link" href={job.video_url} target="_blank" rel="noreferrer">{job.video_url} ↗</a>}</div>
            <div className="job-head-actions"><span className={`status ${job.status}`}>{statusLabels[job.status]}</span>{page === 'history' && <button className="history-toggle" aria-expanded={historyExpanded} onClick={() => setExpandedHistoryJobId(historyExpanded ? null : job.id)}>{historyExpanded ? '收起' : '展开'}</button>}</div></div>
          {(page === 'home' || historyExpanded) && <>{job.error && !jobErrorAlreadyShownByStage(job) && <div className="error-box">{job.error}</div>}
          {job.parts.map(part => <div className="part-progress" key={part.id}>
            <div className="part-title"><strong>{part.title}</strong></div>
            <div className="stage-line">{part.stages.map(stage => <div className={`stage ${stage.status}`} key={stage.stage} title={stage.error || ''}>
              <i>{stage.status === 'completed' || stage.status === 'skipped' ? '✓' : stage.status === 'failed' ? '!' : ''}</i>
              <span>{stageLabels[stage.stage]}</span>
              {stage.status === 'failed' && <button onClick={async () => {
                try { await api.retry(job.id, part.id, stage.stage); await refresh() } catch (error) { setNotice(errorText(error)) }
              }}>从此重试</button>}
            </div>)}</div>
            {part.stages.find(s => s.status === 'failed')?.error && <p className="stage-error">{part.stages.find(s => s.status === 'failed')?.error}</p>}
            <div className="document-actions">
              {part.artifacts.filter(a => a.kind === 'transcript').map(transcript => <button key={transcript.id} className="ghost" onClick={() => void showTranscript(transcript.id, part.title)}>查看转写</button>)}
              {part.artifacts.filter(a => a.kind === 'document').map(doc => <button key={doc.id} className="ghost" onClick={() => void showDocument(doc.id, part.title)}>预览知识正文</button>)}
              {part.artifacts.some(a => a.kind === 'topic') && <button className="ghost" title="只显示本次归档新增的内容" onClick={() => void showTopics(part.artifacts.filter(a => a.kind === 'topic'), part.artifacts.find(a => a.kind === 'knowledge_update'), part.title)}>查看归档主题（{part.artifacts.filter(a => a.kind === 'topic').length}）</button>}
              {part.artifacts.some(a => a.kind === 'document') && !['queued', 'running'].includes(job.status) && <button className="ghost" onClick={() => void retryOrganize(job.id, part.id)}>重新归档知识</button>}
            </div>
          </div>)}
          {['queued', 'running'].includes(job.status) && <button className="cancel" onClick={async () => { try { await api.cancel(job.id); await refresh() } catch (error) { setNotice(errorText(error)) } }}>取消任务</button>}
          {['failed', 'cancelled'].includes(job.status) && !hasKnowledgeOutput(job) && <div className="failed-job-actions"><small>该任务尚未生成知识文档，可以安全清理。</small><button className="ghost danger" disabled={deletingJobId !== null} onClick={() => void deleteFinishedJob(job)}>{deletingJobId === job.id ? '删除中…' : '删除任务'}</button></div>}
          </>}
        </article>})}
      </section>

      {page === 'home' && <section className="card settings">
        <div className="section-heading"><span>03</span><div><h2>服务配置</h2><p>密钥仅从后端环境变量读取，不会发送到此页面。</p></div></div>
        <div className="setting-grid">
          <div><small>语音转写</small><strong>{String(settings.stt_model || '—')}</strong><code>{String(settings.stt_base_url || '')}</code><button className="ghost" onClick={() => void testConnection('stt')}>测试 STT</button></div>
          <div><small>知识稿模型</small><strong>{String(settings.llm_model || '—')}</strong><code>{String(settings.llm_base_url || '')}</code><button className="ghost" onClick={() => void testConnection('llm')}>测试 LLM</button></div>
        </div>
      </section>}
    </main>

    <footer>拾影成文 <span>·</span> 内容只在本机处理与保存 <span>·</span> 请仅处理你有权访问的内容</footer>

    {profileOpen && <div className="modal-backdrop" onMouseDown={() => setProfileOpen(false)}>
      <div className="modal profile-modal" role="dialog" aria-modal="true" aria-label="知识库 Profile 设置" onMouseDown={event => event.stopPropagation()}>
        <header className="profile-modal-header"><div><small>KNOWLEDGE SETTINGS</small><h2>知识库 Profile</h2><p>定义什么值得保留，以及知识最终归到哪里。</p></div><button aria-label="关闭知识库设置" onClick={() => setProfileOpen(false)}>×</button></header>
        <div className="profile-modal-body">
          <div className="profile-tabs" role="tablist" aria-label="知识库设置页面">
            <button role="tab" aria-selected={profileTab === 'editor'} className={profileTab === 'editor' ? 'active' : ''} onClick={() => setProfileTab('editor')}><span>01</span> Profile 配置</button>
            <button role="tab" aria-selected={profileTab === 'guide'} className={profileTab === 'guide' ? 'active' : ''} onClick={() => setProfileTab('guide')}><span>02</span> 使用说明</button>
          </div>
          {profileTab === 'guide' ? <article className="profile-guide">
            <div className="guide-hero"><small>PROFILE PLAYBOOK</small><h2>先决定留下什么，再决定放到哪里</h2><p>Profile 不是提示词堆砌，而是你的长期编辑方针。规则越清楚，知识库越稳定。</p><div className="guide-pipeline"><div><b>01</b><strong>视频内容</strong><span>字幕或语音转写</span></div><i>→</i><div><b>02</b><strong>关注范围</strong><span>筛选值得保留的内容</span></div><i>→</i><div><b>03</b><strong>推荐主题</strong><span>选择合适的知识归属</span></div><i>→</i><div><b>04</b><strong>主题知识</strong><span>新建或合并 Markdown</span></div></div></div>
            <section><span>01</span><div><h3>Profile 是什么？</h3><p>一个 Profile 代表一套独立知识库及其编辑策略。它由整理模式、关注范围和推荐主题共同组成，不同 Profile 的主题、索引和去重范围彼此隔离。</p><div className="guide-callout"><strong>一句话理解</strong><p>关注范围是“编辑方针”，推荐主题是“书架目录”。guided 中它们是优先级，strict 中才是强制过滤和目录限制。</p></div><div className="guide-warning"><strong>来源复用</strong><p>同一视频的转写和知识稿可以用于多个知识库；每个知识库仍会按自己的 Profile 重新路由和归档。</p></div></div></section>
            <section><span>02</span><div><h3>关注范围和推荐主题有什么区别？</h3><div className="guide-compare"><div><small>关注范围 · SCOPE</small><strong>描述优先关注什么</strong><p>guided 中用于优先归类，不会过滤其他有价值内容；strict 中才作为强制收录范围。</p></div><div><small>推荐主题 · ROUTE</small><strong>决定优先归到哪里</strong><p>每个主题需要名称和边界清楚的描述。主题之间应尽量少重叠。</p></div></div></div></section>
            <section><span>03</span><div><h3>选择整理模式</h3><div className="guide-modes"><div><small>探索期</small><strong>开放 · open</strong><p>几乎不限制领域，系统可自由建立主题。适合还不知道知识库结构时使用。</p></div><div className="recommended"><small>推荐</small><strong>引导 · guided</strong><p>优先使用关注范围和推荐主题；匹配不上时，也会为其他有价值的内容自由建立主题。</p></div><div><small>固定目录</small><strong>严格 · strict</strong><p>只能写入推荐主题；超出范围或无法归类的知识会被忽略。</p></div></div></div></section>
            <section><span>04</span><div><h3>如何写关注范围？</h3><p>建议包含三部分：关注的领域、希望保留的内容特征、明确排除项。不要只写关键词。</p><blockquote>关注两性关系中的认知规律，以及线上聊天、语音聊天和线下约会中的沟通技巧；整理能够体现谈吐、促进相互了解的谈资和可执行建议；同时收录星座基础知识及其作为社交谈资的使用方式。优先保留具体、有适用条件、尊重双方边界的内容；忽略广告、操控性话术、外貌打分和缺乏依据的绝对化结论。</blockquote><p className="guide-caption">好的范围既告诉系统“要什么”，也告诉系统“不要什么”。</p></div></section>
            <section><span>05</span><div><h3>如何添加推荐主题？</h3><p>名称负责快速识别，语义描述负责划定边界。描述应回答“这里具体收录什么”，不要重复主题名称。</p><div className="guide-example-grid"><div><small>名称</small><strong>线上聊天技巧</strong></div><div><small>语义描述</small><p>文字聊天中的开场、回应、延续话题、节奏控制、情绪表达，以及从聊天自然过渡到邀约的方法。</p></div></div><div className="guide-tip"><b>避免</b><span>“聊天、恋爱、沟通、技巧”这类纯关键词描述，主题之间会难以区分。</span></div></div></section>
            <section><span>06</span><div><h3>完整例子：两性沟通知识库</h3><div className="guide-walkthrough"><dl><div><dt>Profile 名称</dt><dd>两性沟通与社交谈资</dd></div><div><dt>推荐模式</dt><dd>引导 guided</dd></div><div><dt>关注范围</dt><dd>使用上方示例范围，保留具体、尊重边界且有适用条件的关系与沟通知识。</dd></div></dl><div className="guide-topic-list"><span>两性认知</span><span>线上聊天技巧</span><span>线下约会技巧</span><span>谈资与谈吐</span><span>语音聊天技巧</span><span>星座</span></div><div className="guide-flow"><div><small>同一条视频</small><strong>同时讲线上开场、约会判断与星座谈资</strong></div><b>→</b><div><small>系统处理</small><strong>拆分后分别更新三个主题 Markdown，不把整篇内容塞进一个主题</strong></div></div></div></div></section>
            <section><span>07</span><div><h3>AI 辅助归类什么时候用？</h3><p>新增主题时，AI 会比较现有目录：语义相同则建议复用，边界确实不同才建立新路径。它解决的是“目录去重”，不会替你编写关注范围。</p><ul><li>新主题与旧主题名字不同，但含义可能相同</li><li>不确定应该放在一级还是二级目录</li><li>主题越来越多，担心出现重复分类</li></ul></div></section>
            <section><span>08</span><div><h3>保存、启用、删除与后续调整</h3><p>保存只更新 Profile 内容；“设为当前使用”决定新任务采用哪套规则。修改 Profile 不会自动重写历史文档，之后处理的新视频会使用最新规则。</p><div className="guide-delete-rules"><div><b>多个 Profile</b><span>可以删除不再使用的非当前 Profile。</span></div><div><b>当前使用项</b><span>不能直接删除；先启用另一个 Profile，再回来删除。</span></div><div><b>最后一个 Profile</b><span>必须保留，确保新任务始终有可用规则。</span></div><div><b>已有知识内容</b><span>删除 Profile 不会删除主题 Markdown、转写或历史任务。</span></div></div><div className="guide-checklist"><span>✓ 初期优先用 guided</span><span>✓ 推荐主题先控制在 5–10 个</span><span>✓ 发现经常误归类时再细化描述</span><span>✓ 不要频繁改动已有主题含义</span></div></div></section>
          </article> : <div className="profile-workspace">
            <aside className="profile-sidebar">
              <div className="profile-sidebar-head"><div><small>YOUR PROFILES</small><strong>知识库列表</strong></div><button aria-label="新建 Profile" onClick={newProfile}>＋</button></div>
              <div className="profile-list">
                {!profileDraft?.id && <button className="profile-list-item active"><span className="profile-avatar">新</span><span><strong>新知识库</strong><small>尚未保存</small></span></button>}
                {profiles.map(profile => <button key={profile.id} className={`profile-list-item ${profileDraft?.id === profile.id ? 'active' : ''}`} onClick={() => selectProfile(profile.id)}><span className="profile-avatar">{profile.name.trim().slice(0, 1) || '知'}</span><span><strong>{profile.name}</strong><small>{profile.is_active ? '● 当前使用' : `${profile.preferred_topics.length} 个推荐主题`}</small></span></button>)}
              </div>
              <div className="profile-sidebar-note"><b>提示</b><p>通常一个长期关注方向只需要一个 Profile。</p></div>
            </aside>
            <div className="profile-editor">
              {profileDraft && <div className="profile-form">
                <div className="editor-titlebar"><div><small>{profileDraft.id ? 'EDITING PROFILE' : 'NEW PROFILE'}</small><h2>{profileDraft.name || '创建一套知识库规则'}</h2><p>设置内容筛选边界与稳定的主题目录。</p></div>{profileDraft.is_active && <span className="active-badge">● 当前使用</span>}</div>

                <section className="editor-section basic-section"><div className="editor-section-heading"><span>01</span><div><h3>基本信息</h3><p>用一个容易识别的名字区分知识库用途。</p></div></div><label><small>PROFILE 名称</small><input aria-label="Profile 名称" value={profileDraft.name} onChange={event => setProfileDraft({ ...profileDraft, name: event.target.value })} placeholder="例如：两性沟通与社交谈资"/></label></section>

                <section className="editor-section"><div className="editor-section-heading"><span>02</span><div><h3>整理模式</h3><p>决定系统可以多自由地创建和选择主题。</p></div></div><div className="mode-picker" role="radiogroup" aria-label="Profile 模式">{([
                  ['open', '开放', '自由发现和建立主题'], ['guided', '引导', '优先推荐主题，其他内容也可自由新建'], ['strict', '严格', '只能使用推荐主题'],
                ] as const).map(([mode, name, description]) => <button key={mode} role="radio" aria-checked={profileDraft.mode === mode} className={profileDraft.mode === mode ? 'selected' : ''} onClick={() => setProfileDraft({ ...profileDraft, mode, rules: { ignore_out_of_scope: mode === 'strict', merge_similar: true } })}><i>{profileDraft.mode === mode ? '✓' : ''}</i><span><strong>{name}</strong><small>{mode}</small><p>{description}</p></span></button>)}</div></section>

                <section className="editor-section scope-section"><div className="editor-section-heading"><span>03</span><div><h3>关注范围</h3><p>决定从视频中保留什么，也可以明确写出要忽略什么。</p></div><em>内容过滤器</em></div><label><textarea aria-label="Profile 关注范围" value={profileDraft.scope} onChange={event => setProfileDraft({ ...profileDraft, scope: event.target.value })} placeholder="例如：关注两性关系中的认知规律，以及线上聊天、语音聊天和线下约会中的沟通技巧；忽略广告、操控性话术和缺乏依据的绝对化结论。"/><small className="field-help">建议写成完整句子：关注领域 + 保留标准 + 排除项。</small></label></section>

                <section className="editor-section topics-section"><div className="editor-section-heading"><span>04</span><div><h3>推荐主题</h3><p>决定保留下来的知识优先归到哪里。</p></div><button className="ghost" onClick={() => setProfileDraft({ ...profileDraft, preferred_topics: [...profileDraft.preferred_topics, { name: '', description: '', path: '' }] })}>＋ 添加主题</button></div><div className="topic-editor">
                  {!profileDraft.preferred_topics.length && <div className="empty-topic"><b>还没有推荐主题</b><p>{profileDraft.mode === 'strict' ? '严格模式至少需要一个主题，否则所有内容都会被忽略。' : '系统仍可自由创建主题；添加推荐主题能让目录更稳定。'}</p><button className="ghost" onClick={() => setProfileDraft({ ...profileDraft, preferred_topics: [{ name: '', description: '', path: '' }] })}>添加第一个主题</button></div>}
                  {profileDraft.preferred_topics.map((topic, index) => <div className="topic-row" key={`${index}-${topic.path}`}><div className="topic-card-head"><span className="topic-number">{String(index + 1).padStart(2, '0')}</span><label><small>主题名称</small><input aria-label={`主题名称 ${index + 1}`} value={topic.name} onChange={event => updateTopic(index, 'name', event.target.value)} placeholder="例如：线上聊天技巧"/></label><button aria-label={`移除主题 ${index + 1}`} className="remove-topic" onClick={() => setProfileDraft({ ...profileDraft, preferred_topics: profileDraft.preferred_topics.filter((_, topicIndex) => topicIndex !== index) })}>×</button></div><label className="topic-description"><small>语义描述</small><textarea aria-label={`语义描述 ${index + 1}`} value={topic.description} onChange={event => updateTopic(index, 'description', event.target.value)} placeholder="说明这个主题具体收录什么内容，以及与其他主题的边界。"/></label><div className="topic-card-footer">{topic.path ? <code>{topic.path}</code> : <span>保存时会自动生成归类路径</span>}{!topic.path && <button className="ghost" onClick={() => void suggestTopic(index)}>AI 辅助归类</button>}</div></div>)}
                </div></section>

                <div className="profile-save"><div>{profileDraft.id && !profileDraft.is_active && profiles.length > 1 && <button className="text-button danger" onClick={() => void deleteProfile()}>删除 Profile</button>}{profileDraft.is_active && profiles.length > 1 && <small className="profile-delete-hint">当前使用项需先切换后才能删除</small>}<button className="text-button" disabled={!profileDraft} onClick={exportProfile}>导出 JSON</button></div><div>{profileDraft.id && !profileDraft.is_active && <button className="ghost" onClick={() => void activateProfile()}>设为当前使用</button>}<button className="primary" disabled={busy || !profileDraft.name.trim()} onClick={() => void saveProfile()}>{busy ? '保存中…' : '保存 Profile'}</button></div></div>
              </div>}
            </div>
          </div>}
        </div>
      </div>
    </div>}

    {knowledgeOpen && <div className="modal-backdrop" onMouseDown={() => setKnowledgeOpen(false)}>
      <div className="modal knowledge-browser" role="dialog" aria-modal="true" aria-label="知识库目录" onMouseDown={event => event.stopPropagation()}>
        <header><div><small>KNOWLEDGE BASE</small><h2>{profiles.find(profile => profile.id === knowledgeProfileId)?.name || '知识库'}</h2><p>仅展示已归档的主题知识</p></div><label className="knowledge-profile-select"><small>知识库</small><select aria-label="浏览知识库" value={knowledgeProfileId} onChange={event => void switchKnowledgeProfile(event.target.value)}>{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label><button aria-label="关闭知识库目录" onClick={() => setKnowledgeOpen(false)}>×</button></header>
        <div className="knowledge-browser-actions">
          <span>知识库名称 → 主题分类 → Markdown</span>
          <div><button className="ghost" onClick={() => void openKnowledge()}>刷新</button></div>
        </div>
        <div className="knowledge-browser-body">
          <aside aria-label="知识库文件树">
            {knowledgeLoading ? <div className="browser-empty">正在读取目录…</div> : !knowledgeFiles.length ? <div className="browser-empty">知识库还是空的</div> : <KnowledgeTree entries={knowledgeFiles} expanded={expandedPaths} selectedPath={knowledgeSelection?.entry.path} onToggle={toggleKnowledgeDirectory} onSelect={entry => void selectKnowledgeFile(entry)}/>}
          </aside>
          <section className="knowledge-file-preview">
            {!knowledgeSelection ? <div className="browser-placeholder"><b>选择一个文件</b><p>Markdown、JSON 和 TXT 文件可直接预览。</p></div> : <>
              <div className="knowledge-file-head"><div><strong>{knowledgeSelection.entry.name}</strong><small>{knowledgeSelection.entry.path} · {fileSize(knowledgeSelection.entry.size)}</small></div><div className="knowledge-file-buttons"><button className="ghost" title="合并重复内容并重新组织知识层级" disabled={!knowledgeSelection.entry.name.toLowerCase().endsWith('.md') || refactoringPath !== null} onClick={() => setRefactorConfirmOpen(true)}>{refactoringPath === knowledgeSelection.entry.path ? '整理中…' : '整理合并'}</button>{knowledgeSelection.content && <a className="ghost button-link" href={api.knowledgePdfUrl(knowledgeSelection.entry.path, knowledgeProfileId)}>导出 PDF</a>}</div></div>
              {!knowledgeSelection.entry.previewable ? <div className="browser-placeholder"><b>该文件不支持在线预览</b><p>暂不支持导出 PDF。</p></div> : knowledgeSelection.content === undefined ? <div className="browser-placeholder">正在加载内容…</div> : knowledgeSelection.entry.name.toLowerCase().endsWith('.md') || knowledgeSelection.entry.name.toLowerCase().endsWith('.markdown') ? <div className="markdown"><MarkdownView content={knowledgeSelection.content}/></div> : <pre className="plain-preview">{knowledgeSelection.content}</pre>}
            </>}
          </section>
        </div>
      </div>
    </div>}

    {refactorConfirmOpen && knowledgeSelection && <div className="confirm-backdrop" onMouseDown={() => setRefactorConfirmOpen(false)}>
      <div className="confirm-dialog" role="alertdialog" aria-modal="true" aria-label="确认整理合并" onMouseDown={event => event.stopPropagation()}>
        <span className="confirm-icon">⌘</span>
        <small>MERGE & RESTRUCTURE</small>
        <h3>整理合并「{knowledgeSelection.entry.name.replace(/\.md$/i, '')}」？</h3>
        <p>AI 会把相似内容合并成更完整的讨论，并重新组织知识层级，让主题更易读。“我的笔记”会原样保留。</p>
        <div><button className="ghost" onClick={() => setRefactorConfirmOpen(false)}>取消</button><button className="primary" onClick={() => void refactorKnowledgeFile()}>确认整理</button></div>
      </div>
    </div>}

    {regenerateConfirmOpen && <div className="confirm-backdrop" onMouseDown={() => setRegenerateConfirmOpen(false)}>
      <div className="confirm-dialog" role="alertdialog" aria-modal="true" aria-label="确认重新归档知识库" onMouseDown={event => event.stopPropagation()}>
        <span className="confirm-icon danger-icon">!</span>
        <small>REORGANIZE KNOWLEDGE BASE</small>
        <h3>重新归档当前启用的知识库？</h3>
        <p>当前知识库的归档主题会被清空并重建；转写和知识稿会保留，不会再次调用知识稿模型。</p>
        <div><button className="ghost" onClick={() => setRegenerateConfirmOpen(false)}>取消</button><button className="primary" onClick={() => void regenerateKnowledgeBase()}>确认重新归档</button></div>
      </div>
    </div>}

    {preview && <div className="modal-backdrop" onMouseDown={() => setPreview(null)}>
      <div className="modal" role="dialog" aria-modal="true" onMouseDown={event => event.stopPropagation()}>
        <header><div><small>{preview.kind === 'document' ? 'MARKDOWN PREVIEW' : 'INTERMEDIATE TRANSCRIPT'}</small><h2>{preview.title}</h2></div><button onClick={() => setPreview(null)}>×</button></header>
        <div className="modal-actions"><button className="ghost" onClick={() => void navigator.clipboard.writeText(preview.content).then(() => setNotice('已复制内容'))}>复制内容</button></div>
        <div className="markdown"><MarkdownView content={preview.content}/></div>
      </div>
    </div>}
  </>
}
