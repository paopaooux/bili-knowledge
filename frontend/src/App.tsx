import { useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from './api'
import type { Inspection, Job, KnowledgeProfile, StageName, Status } from './types'

const stageLabels: Record<StageName, string> = {
  parse: '解析', acquire: '获取素材', transcribe: '转写', generate: '生成知识稿', organize: '归档知识', publish: '发布',
}

const statusLabels: Record<Status, string> = {
  pending: '等待', queued: '排队', running: '处理中', completed: '完成', failed: '失败',
  cancelled: '已取消', skipped: '已复用',
}

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

export default function App() {
  const [url, setUrl] = useState('')
  const [inspection, setInspection] = useState<Inspection | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [settings, setSettings] = useState<Record<string, string | boolean | null>>({})
  const [profiles, setProfiles] = useState<KnowledgeProfile[]>([])
  const [profileDraft, setProfileDraft] = useState<KnowledgeProfile | null>(null)
  const [profileOpen, setProfileOpen] = useState(false)
  const [profileTab, setProfileTab] = useState<'editor' | 'guide'>('editor')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [preview, setPreview] = useState<{ title: string; content: string; id: string; kind: 'document' | 'transcript' } | null>(null)

  const active = useMemo(() => jobs.some(job => ['queued', 'running'].includes(job.status)), [jobs])

  const refresh = async () => {
    try { setJobs(await api.jobs()) } catch (error) { setNotice(errorText(error)) }
  }

  const loadProfiles = async (preferredId?: string) => {
    const result = await api.profiles()
    setProfiles(result)
    const selected = result.find(profile => profile.id === preferredId)
      || result.find(profile => profile.is_active)
      || result[0]
    setProfileDraft(selected ? JSON.parse(JSON.stringify(selected)) as KnowledgeProfile : null)
  }

  useEffect(() => {
    void refresh()
    api.settings().then(setSettings).catch(error => setNotice(errorText(error)))
    loadProfiles().catch(error => setNotice(errorText(error)))
  }, [])

  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => void refresh(), 2000)
    return () => window.clearInterval(timer)
  }, [active])

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
    if (!inspection?.parts[0]) return
    setBusy(true); setNotice('')
    try {
      await api.createJob(inspection.id, [inspection.parts[0].id])
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
    <header className="hero">
      <nav><span className="brand"><img src="/favicon.svg" alt=""/>拾影成文</span><div className="nav-actions"><button onClick={() => { setProfileTab('editor'); setProfileOpen(true) }}>知识库设置</button><span className="local-pill">● 本地运行</span></div></nav>
      <div className="hero-copy">
        <p className="eyebrow">BILIBILI → KNOWLEDGE</p>
        <h1>让视频的价值，<br/><em>沉淀为可引用的知识。</em></h1>
        <p>字幕优先 · 自动转写 · 时间戳引用 · Markdown 永久保存</p>
      </div>
    </header>

    <main>
      {notice && <div className="notice" role="status">{notice}<button onClick={() => setNotice('')}>×</button></div>}

      <section className="card create-card">
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
          <button className="primary submit" disabled={busy || !inspection.parts.length} onClick={() => void submit()}>生成知识文档 →</button>
        </div>}
      </section>

      <section className="tasks">
        <div className="section-heading"><span>02</span><div><h2>整理队列</h2><p>刷新页面或重启后端，任务记录仍会保留。</p></div><button className="ghost" onClick={() => void refresh()}>刷新</button></div>
        {!jobs.length && <div className="empty">还没有任务。提交第一个视频后，处理进度会显示在这里。</div>}
        {jobs.map(job => <article className="job-card" key={job.id}>
          <div className="job-head"><div><span>{job.bvid}</span><h3>{job.video_title}</h3><small>{new Date(job.created_at).toLocaleString()}</small></div>
            <span className={`status ${job.status}`}>{statusLabels[job.status]}</span></div>
          {job.error && <div className="error-box">{job.error}</div>}
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
              {part.artifacts.filter(a => a.kind === 'transcript').map(transcript => <span key={transcript.id}>
                <button className="ghost" onClick={() => void showTranscript(transcript.id, part.title)}>查看转写（中间态）</button>
                <a className="ghost" href={`/api/transcripts/${transcript.id}/download`}>下载 JSON</a>
              </span>)}
              {part.artifacts.filter(a => a.kind === 'document').map(doc => <span key={doc.id}>
              <button className="ghost" onClick={() => void showDocument(doc.id, part.title)}>预览</button>
              <a className="ghost" href={`/api/documents/${doc.id}/download`}>下载 Markdown</a>
              </span>)}
              {part.artifacts.filter(a => a.kind === 'topic').map(topic => <span key={topic.id}>
              <button className="ghost" onClick={() => void showDocument(topic.id, `${part.title} · 主题知识`)}>查看归类主题</button>
              <a className="ghost" href={`/api/documents/${topic.id}/download`}>下载主题 Markdown</a>
              </span>)}
            </div>
          </div>)}
          {['queued', 'running'].includes(job.status) && <button className="cancel" onClick={async () => { try { await api.cancel(job.id); await refresh() } catch (error) { setNotice(errorText(error)) } }}>取消任务</button>}
        </article>)}
      </section>

      <section className="card settings">
        <div className="section-heading"><span>03</span><div><h2>服务配置</h2><p>密钥仅从后端环境变量读取，不会发送到此页面。</p></div></div>
        <div className="setting-grid">
          <div><small>语音转写</small><strong>{String(settings.stt_model || '—')}</strong><code>{String(settings.stt_base_url || '')}</code><button className="ghost" onClick={() => void testConnection('stt')}>测试 STT</button></div>
          <div><small>知识稿模型</small><strong>{String(settings.llm_model || '—')}</strong><code>{String(settings.llm_base_url || '')}</code><button className="ghost" onClick={() => void testConnection('llm')}>测试 LLM</button></div>
          <div><small>知识库</small><strong>{profiles.find(profile => profile.is_active)?.name || 'Markdown 知识库'}</strong><code>{String(settings.knowledge_base_dir || '')}</code><div className="setting-actions"><button className="ghost" onClick={() => { setProfileTab('editor'); setProfileOpen(true) }}>管理 Profile</button><button className="ghost" onClick={async () => { try { await api.openOutput() } catch (error) { setNotice(errorText(error)) } }}>打开目录</button></div></div>
        </div>
      </section>
    </main>

    <footer>拾影成文 <span>·</span> 内容只在本机处理与保存 <span>·</span> 请仅处理你有权访问的内容</footer>

    {profileOpen && <div className="modal-backdrop" onMouseDown={() => setProfileOpen(false)}>
      <div className="modal profile-modal" role="dialog" aria-modal="true" aria-label="知识库 Profile 设置" onMouseDown={event => event.stopPropagation()}>
        <header><div><small>KNOWLEDGE SETTINGS</small><h2>知识库 Profile</h2></div><button aria-label="关闭知识库设置" onClick={() => setProfileOpen(false)}>×</button></header>
        <div className="profile-modal-body">
          <div className="profile-tabs" role="tablist" aria-label="知识库设置页面">
            <button role="tab" aria-selected={profileTab === 'editor'} className={profileTab === 'editor' ? 'active' : ''} onClick={() => setProfileTab('editor')}>Profile 配置</button>
            <button role="tab" aria-selected={profileTab === 'guide'} className={profileTab === 'guide' ? 'active' : ''} onClick={() => setProfileTab('guide')}>使用说明</button>
          </div>
          {profileTab === 'guide' ? <article className="profile-guide">
            <section><span>01</span><div><h3>Profile 是什么？</h3><p>Profile 决定系统从视频中重点保留什么知识，以及优先整理到哪些主题。它只影响知识归类，不会修改原始知识稿和转写内容。</p></div></section>
            <section><span>02</span><div><h3>选择整理模式</h3><div className="guide-modes"><div><strong>开放 open</strong><p>不限制领域，让 AI 根据视频自由建立主题，适合通用知识库。</p></div><div><strong>引导 guided</strong><p>优先使用推荐主题，同时允许创建范围内的新主题。通常最实用。</p></div><div><strong>严格 strict</strong><p>只能写入推荐主题，范围外内容直接忽略，适合目标非常明确的资料库。</p></div></div></div></section>
            <section><span>03</span><div><h3>如何写关注范围？</h3><p>用自然语言说明“想保留什么”和“应该忽略什么”。例如：</p><blockquote>提取学习方法、时间管理、沟通协作和健康习惯中可验证、可执行的知识；忽略广告、重复口号和无关内容。</blockquote></div></section>
            <section><span>04</span><div><h3>如何添加推荐主题？</h3><p>只填写主题名称和语义描述。描述应该说明该主题收录哪些内容，而不是堆关键词。</p><div className="guide-example"><small>示例主题</small><strong>学习方法</strong><p>阅读、记忆、练习、复盘以及建立长期学习习惯的方法。</p></div></div></section>
            <section><span>05</span><div><h3>AI 辅助归类</h3><p>添加新主题后点击“AI 辅助归类”。LLM 会比较已有主题：语义相同时建议复用，确实不同时建立新主题。若 AI 暂时不可用，保存时系统也会自动完成归类。</p></div></section>
            <section><span>06</span><div><h3>完整例子：个人成长知识库</h3><div className="guide-walkthrough"><dl><div><dt>名称</dt><dd>个人成长与学习</dd></div><div><dt>模式</dt><dd>引导 guided</dd></div><div><dt>关注范围</dt><dd>提取学习方法、时间管理、沟通协作和健康习惯中可执行的知识；忽略广告和无关内容。</dd></div></dl><div className="guide-topic-list"><span>学习方法</span><span>时间管理</span><span>沟通协作</span><span>健康习惯</span></div><div className="guide-flow"><div><small>视频内容</small><strong>“每周复盘时记录有效学习策略……”</strong></div><b>→</b><div><small>系统处理</small><strong>识别为“学习方法”，与已有相似观点合并</strong></div></div></div></div></section>
            <section><span>07</span><div><h3>保存与启用</h3><p>“保存 Profile”只保存编辑内容；只有标记为“当前使用”的 Profile 会被新任务采用。正在处理的单次归档会使用读取时的 Profile 内容。</p></div></section>
          </article> : <>
          <p className="profile-intro">设置希望保留的知识范围和推荐主题，只需填写自然语言。</p>
          <div className="profile-toolbar">
            <label><small>正在编辑</small><select aria-label="选择知识库 Profile" value={profileDraft?.id || ''} onChange={event => selectProfile(event.target.value)}>
              {!profileDraft?.id && <option value="">新知识库（尚未保存）</option>}
              {profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.is_active ? '● ' : ''}{profile.name}</option>)}
            </select></label>
            <button className="ghost" onClick={newProfile}>新建</button>
            <button className="ghost" disabled={!profileDraft} onClick={exportProfile}>导出 JSON</button>
          </div>
          {profileDraft && <div className="profile-form">
            <div className="profile-fields">
              <label><small>名称</small><input aria-label="Profile 名称" value={profileDraft.name} onChange={event => setProfileDraft({ ...profileDraft, name: event.target.value })}/></label>
              <label><small>模式</small><select aria-label="Profile 模式" value={profileDraft.mode} onChange={event => { const mode = event.target.value as KnowledgeProfile['mode']; setProfileDraft({ ...profileDraft, mode, rules: { ignore_out_of_scope: mode !== 'open', merge_similar: true } }) }}>
                <option value="open">开放 · 自由归类</option><option value="guided">引导 · 优先推荐主题</option><option value="strict">严格 · 仅限推荐主题</option>
              </select></label>
            </div>
            <label className="scope-field"><small>关注范围</small><textarea aria-label="Profile 关注范围" value={profileDraft.scope} onChange={event => setProfileDraft({ ...profileDraft, scope: event.target.value })} placeholder="描述希望从视频中保留哪些知识，以及应该忽略什么。"/></label>
            <div className="topic-heading"><div><h3>推荐主题</h3><p>只需填写名称和描述，系统会自动处理归类位置。</p></div><button className="ghost" onClick={() => setProfileDraft({ ...profileDraft, preferred_topics: [...profileDraft.preferred_topics, { name: '', description: '', path: '' }] })}>＋ 添加主题</button></div>
            <div className="topic-editor">
              {!profileDraft.preferred_topics.length && <div className="empty-topic">当前没有推荐主题，整理器会按照模式自由处理。</div>}
              {profileDraft.preferred_topics.map((topic, index) => <div className="topic-row" key={`${index}-${topic.path}`}>
                <label><small>主题名称</small><input value={topic.name} onChange={event => updateTopic(index, 'name', event.target.value)} placeholder="例如：学习方法"/></label>
                <label><small>语义描述</small><textarea value={topic.description} onChange={event => updateTopic(index, 'description', event.target.value)} placeholder="这个主题应该收录哪些内容？"/></label>
                <div className="topic-actions">{!topic.path && <button className="ghost" onClick={() => void suggestTopic(index)}>AI 辅助归类</button>}<button className="text-button danger" onClick={() => setProfileDraft({ ...profileDraft, preferred_topics: profileDraft.preferred_topics.filter((_, topicIndex) => topicIndex !== index) })}>移除</button></div>
              </div>)}
            </div>
            <div className="profile-save"><button className="primary" disabled={busy || !profileDraft.name.trim()} onClick={() => void saveProfile()}>{busy ? '保存中…' : '保存 Profile'}</button>{profileDraft.id && !profileDraft.is_active && <button className="ghost" onClick={() => void activateProfile()}>设为当前使用</button>}{profileDraft.id && !profileDraft.is_active && <button className="text-button danger" onClick={() => void deleteProfile()}>删除</button>}{profileDraft.is_active && <span className="active-profile">● 当前任务使用此 Profile</span>}</div>
          </div>}
          </>}
        </div>
      </div>
    </div>}

    {preview && <div className="modal-backdrop" onMouseDown={() => setPreview(null)}>
      <div className="modal" role="dialog" aria-modal="true" onMouseDown={event => event.stopPropagation()}>
        <header><div><small>{preview.kind === 'document' ? 'MARKDOWN PREVIEW' : 'INTERMEDIATE TRANSCRIPT'}</small><h2>{preview.title}</h2></div><button onClick={() => setPreview(null)}>×</button></header>
        <div className="modal-actions"><button className="ghost" onClick={() => void navigator.clipboard.writeText(preview.content).then(() => setNotice('已复制内容'))}>复制内容</button><a className="primary" href={preview.kind === 'document' ? `/api/documents/${preview.id}/download` : `/api/transcripts/${preview.id}/download`}>下载</a></div>
        <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{preview.content}</ReactMarkdown></div>
      </div>
    </div>}
  </>
}
