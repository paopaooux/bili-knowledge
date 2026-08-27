import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
import App from './App'

let jobsPayload: unknown[] = []
const defaultProfiles = [{
  id: 'profile-1', name: '个人成长与学习', mode: 'guided', scope: '学习与成长知识',
  preferred_topics: [{ name: '学习方法', path: '个人成长/学习方法.md', description: '学习方法' }],
  rules: { ignore_out_of_scope: false, merge_similar: true }, is_active: true,
  version: 1, created_at: '2026-01-01', updated_at: '2026-01-01',
}]
let profilesPayload = defaultProfiles

vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
  const url = String(input)
  if (url.endsWith('/api/documents/topic-1')) return new Response('---\ntitle: "时间管理"\n---\n\n# 时间管理\n\n每天安排重点任务。')
  if (url.endsWith('/api/documents/topic-2')) return new Response('---\ntitle: "运动习惯"\n---\n\n# 运动习惯\n\n从短时锻炼开始。')
  if (url.endsWith('/api/documents/knowledge-update-1')) return new Response(JSON.stringify({
    plans: [{
      action: 'merge', target_path: 'topics/时间管理.md', title: '时间管理',
      sections: { knowledge: ['本次合并新增的间隔复习要点。\n  - 补充案例：考前一周开始复习'], disagreements: [] },
    }],
  }))
  if (url.endsWith('/api/health')) return new Response(JSON.stringify({ ok: true, worker: 'running' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  if (url.includes('/api/knowledge/file/refactor?path=')) return new Response('# 学习方法\n\n- 有效复习需要调整间隔\n  - 根据遗忘程度逐渐拉长间隔\n\n## 我的笔记\n\n<!-- 保留 -->')
  if (url.includes('/api/knowledge/files?profile_id=')) return new Response(JSON.stringify([{
    name: '个人成长与学习', path: '@knowledge-base', type: 'directory', size: null, modified_at: '2026-01-01', previewable: false,
    children: [{ name: '学习方法.md', path: 'topics/学习方法.md', type: 'file', size: 32, modified_at: '2026-01-01', previewable: true }],
  }]), { status: 200, headers: { 'Content-Type': 'application/json' } })
  if (url.includes('/api/knowledge/file?path=')) return new Response('# 学习方法\n\n- 间隔复习。\n  - 条件：已经理解材料。\n  - 步骤：逐渐拉长间隔。')
  if (url.includes('/api/knowledge/regenerate?profile_id=')) return new Response(JSON.stringify({ queued_jobs: 1, queued_parts: 1 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  const payload = url.endsWith('/api/jobs') ? jobsPayload : url.endsWith('/api/knowledge/profiles')
    ? profilesPayload
    : { stt_model: 'qwen3.5-omni-plus', llm_model: 'test-model', source_output_dir: '/tmp/sources', knowledge_base_dir: '/tmp/kb' }
  return new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } })
}))

afterEach(() => { jobsPayload = []; profilesPayload = defaultProfiles; vi.clearAllMocks() })

test('opens profile management in a separate modal', async () => {
  render(<App />)
  expect(screen.getByText('让视频的价值，')).toBeInTheDocument()
  expect(screen.getByLabelText('Bilibili 视频链接')).toBeInTheDocument()
  expect(await screen.findByText('test-model')).toBeInTheDocument()
  expect(await screen.findByText('● 正常运行')).toBeInTheDocument()
  expect(screen.queryByRole('dialog', { name: '知识库 Profile 设置' })).not.toBeInTheDocument()
  fireEvent.click(await screen.findByRole('button', { name: '知识库设置' }))
  expect(screen.getByRole('dialog', { name: '知识库 Profile 设置' })).toBeInTheDocument()
  expect(await screen.findByDisplayValue('个人成长与学习')).toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: '主题名称 1' })).toHaveValue('学习方法')
  fireEvent.click(screen.getByRole('button', { name: '保存 Profile' }))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: '知识库 Profile 设置' })).not.toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: '知识库设置' }))
  fireEvent.click(screen.getByRole('tab', { name: /使用说明/ }))
  expect(screen.getByText('Profile 是什么？')).toBeInTheDocument()
  expect(screen.getByText('如何添加推荐主题？')).toBeInTheDocument()
  expect(screen.getByText(/分别更新三个主题 Markdown/)).toBeInTheDocument()
})

test('groups all archived topics into one inline action', async () => {
  jobsPayload = [{
    id: 'job-1', video_title: '个人成长课程', bvid: 'BV1TEST', status: 'completed',
    created_at: '2026-01-01', artifacts: [], parts: [{
      id: 'part-1', part_index: 1, title: '第一部分', status: 'completed', stages: [],
      artifacts: [
        { id: 'transcript-1', kind: 'transcript', path: '/tmp/transcript.json' },
        { id: 'document-1', kind: 'document', path: '/tmp/document.md' },
        { id: 'topic-1', kind: 'topic', path: '/tmp/topics/时间管理.md' },
        { id: 'topic-2', kind: 'topic', path: '/tmp/topics/运动习惯.md' },
        { id: 'knowledge-update-1', kind: 'knowledge_update', path: '/tmp/knowledge-update.json' },
      ],
    }],
  }]

  render(<App />)

  const transcript = await screen.findByRole('button', { name: '查看转写' })
  const document = screen.getByRole('button', { name: '预览知识正文' })
  const topics = screen.getByRole('button', { name: '查看归档主题（2）' })
  const retry = screen.getByRole('button', { name: '重新归档知识' })
  expect(transcript.parentElement).toBe(document.parentElement)
  expect(document.parentElement).toBe(topics.parentElement)
  expect(topics.parentElement).toBe(retry.parentElement)
  expect(screen.queryByRole('button', { name: /查看主题：/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '查看本次新增' })).not.toBeInTheDocument()

  fireEvent.click(topics)
  expect(await screen.findByRole('heading', { name: '本次归档新增' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: /合并「时间管理」/ })).toBeInTheDocument()
  expect(screen.getByText('本次合并新增的间隔复习要点。')).toBeInTheDocument()
  expect(screen.getByText('补充案例：考前一周开始复习')).toBeInTheDocument()
  expect(screen.queryByText('每天安排重点任务。')).not.toBeInTheDocument()
})

test('browses the knowledge directory and previews markdown in the page', async () => {
  render(<App />)

  fireEvent.click(await screen.findByRole('button', { name: '浏览知识库' }))
  const dialog = await screen.findByRole('dialog', { name: '知识库目录' })
  expect(dialog).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /个人成长与学习/ })).toBeInTheDocument()
  fireEvent.click(await screen.findByRole('button', { name: /学习方法\.md/ }))
  const summary = await screen.findByText('间隔复习。')
  expect(summary.closest('details')).not.toHaveAttribute('open')
  fireEvent.click(summary)
  expect(screen.getByText('条件：已经理解材料。')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '导出 PDF' })).toHaveAttribute(
    'href', '/api/knowledge/file/pdf?path=topics%2F%E5%AD%A6%E4%B9%A0%E6%96%B9%E6%B3%95.md&profile_id=profile-1',
  )
})

test('opens the knowledge browser from the top navigation', async () => {
  render(<App />)

  const browseButtons = await screen.findAllByRole('button', { name: '浏览知识库' })
  fireEvent.click(browseButtons[0])
  expect(await screen.findByRole('dialog', { name: '知识库目录' })).toBeInTheDocument()
})

test('refactors the selected topic into a semantic hierarchy', async () => {
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '浏览知识库' }))
  fireEvent.click(await screen.findByRole('button', { name: /学习方法\.md/ }))
  fireEvent.click(await screen.findByRole('button', { name: '整理合并' }))
  expect(screen.getByRole('alertdialog', { name: '确认整理合并' })).toBeInTheDocument()
  expect(fetch).not.toHaveBeenCalledWith(expect.stringContaining('/refactor'), expect.anything())
  fireEvent.click(screen.getByRole('button', { name: '确认整理' }))

  expect(await screen.findByText('有效复习需要调整间隔')).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith(
    '/api/knowledge/file/refactor?path=topics%2F%E5%AD%A6%E4%B9%A0%E6%96%B9%E6%B3%95.md&profile_id=profile-1',
    expect.objectContaining({ method: 'POST' }),
  )
})

test('retries only the organize stage from a completed job', async () => {
  jobsPayload = [{
    id: 'job-2', video_title: '学习课程', bvid: 'BV2TEST', status: 'completed',
    created_at: '2026-01-01', artifacts: [], parts: [{
      id: 'part-2', part_index: 1, title: '正片', status: 'completed', stages: [],
      artifacts: [{ id: 'document-2', kind: 'document', path: '/tmp/document.md' }],
    }],
  }]
  render(<App />)

  fireEvent.click(await screen.findByRole('button', { name: '重新归档知识' }))

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    '/api/jobs/job-2/retry',
    expect.objectContaining({ method: 'POST', body: JSON.stringify({ part_id: 'part-2', stage: 'organize' }) }),
  ))
  expect(await screen.findByText(/不会重复转写或生成知识正文/)).toBeInTheDocument()
})

test('shows a stage failure only once when the job has the same error', async () => {
  const error = '知识更新计划未通过校验：related_paths 只能包含最多 5 个已有主题'
  jobsPayload = [
    {
      id: 'job-failed', video_title: '失败视频', bvid: 'BVFAILED', status: 'failed', error, profile_id: 'profile-1',
      created_at: '2026-01-01', artifacts: [], parts: [{
        id: 'part-failed', part_index: 1, title: '正片', status: 'failed', artifacts: [],
        stages: [
          { stage: 'transcribe', status: 'completed', retries: 0 },
          { stage: 'organize', status: 'failed', error, retries: 0 },
        ],
      }],
    },
    {
      id: 'other-profile-failed', video_title: '其他知识库失败视频', bvid: 'BVOTHER',
      status: 'failed', error: '其他库失败', profile_id: 'profile-2', created_at: '2026-01-02', artifacts: [],
      parts: [{
        id: 'other-part', part_index: 1, title: '正片', status: 'failed', artifacts: [],
        stages: [{ stage: 'organize', status: 'failed', error: '其他库失败', retries: 0 }],
      }],
    },
  ]

  render(<App />)

  expect(await screen.findByText(error)).toBeInTheDocument()
  expect(screen.getAllByText(error)).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: '历史任务' }))
  fireEvent.click(screen.getByRole('button', { name: '一键重试当前知识库失败任务（1）' }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    '/api/jobs/job-failed/retry',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ part_id: 'part-failed', stage: 'organize' }),
    }),
  ))
  expect(fetch).not.toHaveBeenCalledWith(
    '/api/jobs/other-profile-failed/retry',
    expect.anything(),
  )
  expect(await screen.findByText('已将 1 条失败任务从各自失败阶段重新加入队列')).toBeInTheDocument()
})

test('includes transcription failures in one-click retry', async () => {
  jobsPayload = [{
    id: 'job-asr-failed', video_title: '转写失败视频', bvid: 'BVASRFAILED', status: 'failed', profile_id: 'profile-1',
    created_at: '2026-01-01', artifacts: [], parts: [{
      id: 'part-asr-failed', part_index: 1, title: '正片', status: 'failed', artifacts: [],
      stages: [{ stage: 'transcribe', status: 'failed', error: '转写失败', retries: 0 }],
    }],
  }]
  render(<App />)

  expect(await screen.findByText('转写失败视频')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '历史任务' }))
  fireEvent.click(screen.getByRole('button', { name: '一键重试当前知识库失败任务（1）' }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    '/api/jobs/job-asr-failed/retry',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ part_id: 'part-asr-failed', stage: 'transcribe' }),
    }),
  ))
})

test('allows a cancelled job to be deleted from history', async () => {
  jobsPayload = [{
    id: 'job-cancelled', video_title: '已取消视频', bvid: 'BVCANCELLED', status: 'cancelled',
    created_at: '2026-01-01', artifacts: [], parts: [{
      id: 'part-cancelled', part_index: 1, title: '正片', status: 'cancelled',
      stages: [], artifacts: [],
    }],
  }]
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  render(<App />)

  fireEvent.click(await screen.findByRole('button', { name: '历史任务' }))
  fireEvent.click(screen.getByRole('button', { name: '展开' }))
  fireEvent.click(screen.getByRole('button', { name: '删除任务' }))

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    '/api/jobs/job-cancelled',
    expect.objectContaining({ method: 'DELETE' }),
  ))
})

test('shows only five recent jobs on home and all searchable jobs in history', async () => {
  jobsPayload = Array.from({ length: 7 }, (_, index) => ({
    id: `job-${index}`, video_title: `历史视频 ${index}`, bvid: `BVHISTORY${index}`,
    status: index === 6 ? 'failed' : 'completed', created_at: `2026-01-0${7 - index}`,
    error: index === 6 ? '测试失败' : undefined, artifacts: [], parts: [],
  }))
  render(<App />)

  expect(await screen.findByText('历史视频 0')).toBeInTheDocument()
  expect(screen.getByText('历史视频 4')).toBeInTheDocument()
  expect(screen.queryByText('历史视频 5')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '历史任务' }))
  expect(await screen.findByText('历史视频 6')).toBeInTheDocument()
  expect(screen.getByText('找到 7 条记录')).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: '展开' })).toHaveLength(7)

  fireEvent.change(screen.getByLabelText('搜索历史任务'), { target: { value: 'BVHISTORY6' } })
  expect(screen.getByText('找到 1 条记录')).toBeInTheDocument()
  expect(screen.getByText('历史视频 6')).toBeInTheDocument()
  expect(screen.queryByText('历史视频 0')).not.toBeInTheDocument()
})

test('shows and filters history jobs by knowledge profile', async () => {
  profilesPayload = [
    defaultProfiles[0],
    {
      ...defaultProfiles[0],
      id: 'profile-2',
      name: '工作知识库',
      is_active: false,
    },
  ]
  jobsPayload = [
    {
      id: 'personal-job', video_title: '个人学习视频', bvid: 'BVPERSONAL', status: 'completed',
      profile_id: 'profile-1', profile_name: '个人成长与学习', created_at: '2026-01-01',
      artifacts: [], parts: [],
    },
    {
      id: 'work-job', video_title: '工作方法视频', bvid: 'BVWORK', status: 'completed',
      profile_id: 'profile-2', profile_name: '工作知识库', created_at: '2026-01-02',
      artifacts: [], parts: [],
    },
  ]
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '历史任务' }))

  expect(screen.getByText('个人成长与学习', { selector: '.job-profile' })).toBeInTheDocument()
  expect(screen.getByText('工作知识库', { selector: '.job-profile' })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('筛选知识库'), { target: { value: 'profile-2' } })

  expect(screen.getByText('工作方法视频')).toBeInTheDocument()
  expect(screen.queryByText('个人学习视频')).not.toBeInTheDocument()
  expect(screen.getByText('找到 1 条记录')).toBeInTheDocument()
})

test('puts running jobs first and keeps the four history status groups', async () => {
  jobsPayload = [
    {
      id: 'new-completed', video_title: '较新的完成任务', bvid: 'BVDONE', status: 'completed',
      created_at: '2026-08-17T12:00:00Z', updated_at: '2026-08-17T12:00:00Z', artifacts: [], parts: [],
    },
    {
      id: 'old-running', video_title: '较早的处理中任务', bvid: 'BVRUN', status: 'running',
      created_at: '2026-08-16T12:00:00Z', updated_at: '2026-08-16T12:00:00Z', artifacts: [], parts: [],
    },
  ]
  render(<App />)

  const headings = await screen.findAllByRole('heading', { level: 3 })
  expect(headings.map(heading => heading.textContent)).toEqual([
    '较早的处理中任务',
    '较新的完成任务',
  ])

  fireEvent.click(screen.getByRole('button', { name: '历史任务' }))
  for (const label of ['全部', '处理中', '已完成', '失败']) {
    expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
  }
})

test('keeps history jobs compact until expanded', async () => {
  jobsPayload = [{
    id: 'history-detail', video_title: '可展开视频', bvid: 'BVEXPAND', status: 'completed',
    video_url: 'https://www.bilibili.com/video/BVEXPAND',
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-02-03T04:05:00Z', artifacts: [], parts: [{
      id: 'part-expand', part_index: 1, title: '正片', status: 'completed', artifacts: [],
      stages: [{ stage: 'parse', status: 'completed', retries: 0 }],
    }],
  }]
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '历史任务' }))

  expect(screen.getByText(/最后更新：/)).toHaveTextContent(new Date('2026-02-03T04:05:00Z').toLocaleString())
  expect(screen.getByRole('link', { name: /https:\/\/www\.bilibili\.com\/video\/BVEXPAND/ })).toHaveAttribute(
    'href', 'https://www.bilibili.com/video/BVEXPAND',
  )
  expect(screen.queryByText('解析')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '展开' }))
  expect(screen.getByText('解析')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '收起' })).toBeInTheDocument()
})

test('keeps expanded markdown sections open when the parent view rerenders', async () => {
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '浏览知识库' }))
  fireEvent.click(await screen.findByTitle('topics/学习方法.md'))

  const summary = await screen.findByText('间隔复习。')
  const details = summary.closest('details')
  expect(details).not.toBeNull()
  fireEvent.click(summary.closest('summary')!)
  expect(details).toHaveAttribute('open')

  // Toggling the directory rerenders App, just like the background job polling does.
  fireEvent.click(screen.getByTitle('@knowledge-base'))
  fireEvent.click(screen.getByTitle('@knowledge-base'))

  expect(details).toHaveAttribute('open')
})

test('reorganizes the active knowledge base from history after confirmation', async () => {
  jobsPayload = [{
    id: 'job-regenerate', video_title: '待重建视频', bvid: 'BVREGENERATE', status: 'completed',
    created_at: '2026-01-01', profile_id: 'profile-1', artifacts: [], parts: [],
  }]
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '历史任务' }))
  fireEvent.click(screen.getByRole('button', { name: '重新归档当前知识库' }))

  const dialog = screen.getByRole('alertdialog', { name: '确认重新归档知识库' })
  expect(dialog).toBeInTheDocument()
  expect(screen.getByText(/转写和知识稿会保留/)).toBeInTheDocument()
  expect(fetch).not.toHaveBeenCalledWith(expect.stringContaining('/api/knowledge/regenerate'), expect.anything())
  fireEvent.click(screen.getByRole('button', { name: '确认重新归档' }))

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    '/api/knowledge/regenerate?profile_id=profile-1', expect.objectContaining({ method: 'POST' }),
  ))
  expect(await screen.findByText(/已清空当前知识库的旧归档并重新排队：1 条任务/)).toBeInTheDocument()
})
