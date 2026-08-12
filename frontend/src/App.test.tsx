import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
import App from './App'

let jobsPayload: unknown[] = []

vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
  const url = String(input)
  if (url.endsWith('/api/documents/topic-1')) return new Response('---\ntitle: "时间管理"\n---\n\n# 时间管理\n\n每天安排重点任务。')
  if (url.endsWith('/api/documents/topic-2')) return new Response('---\ntitle: "运动习惯"\n---\n\n# 运动习惯\n\n从短时锻炼开始。')
  if (url.endsWith('/api/health')) return new Response(JSON.stringify({ ok: true, worker: 'running' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  if (url.includes('/api/knowledge/file/refactor?path=')) return new Response('# 学习方法\n\n- 有效复习需要调整间隔\n  - 根据遗忘程度逐渐拉长间隔\n\n## 我的笔记\n\n<!-- 保留 -->')
  if (url.endsWith('/api/knowledge/files')) return new Response(JSON.stringify([{
    name: '个人成长与学习', path: '@knowledge-base', type: 'directory', size: null, modified_at: '2026-01-01', previewable: false,
    children: [{ name: '学习方法.md', path: 'topics/学习方法.md', type: 'file', size: 32, modified_at: '2026-01-01', previewable: true }],
  }]), { status: 200, headers: { 'Content-Type': 'application/json' } })
  if (url.includes('/api/knowledge/file?path=')) return new Response('# 学习方法\n\n- 间隔复习。\n  - 条件：已经理解材料。\n  - 步骤：逐渐拉长间隔。')
  const payload = url.endsWith('/api/jobs') ? jobsPayload : url.endsWith('/api/knowledge/profiles') ? [{
    id: 'profile-1', name: '个人成长与学习', mode: 'guided', scope: '学习与成长知识',
    preferred_topics: [{ name: '学习方法', path: '个人成长/学习方法.md', description: '学习方法' }],
    rules: { ignore_out_of_scope: true, merge_similar: true }, is_active: true,
    version: 1, created_at: '2026-01-01', updated_at: '2026-01-01',
  }] : { stt_model: 'whisper-1', llm_model: 'test-model', source_output_dir: '/tmp/sources', knowledge_base_dir: '/tmp/kb' }
  return new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } })
}))

afterEach(() => { jobsPayload = []; vi.clearAllMocks() })

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

  fireEvent.click(topics)
  expect(await screen.findByRole('heading', { name: '时间管理' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '运动习惯' })).toBeInTheDocument()
  expect(screen.getByText('每天安排重点任务。')).toBeInTheDocument()
  expect(screen.getByText('从短时锻炼开始。')).toBeInTheDocument()
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
  expect(screen.getByRole('link', { name: '下载' })).toHaveAttribute(
    'href', '/api/knowledge/file/download?path=topics%2F%E5%AD%A6%E4%B9%A0%E6%96%B9%E6%B3%95.md',
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
  fireEvent.click(await screen.findByRole('button', { name: '重构知识结构' }))
  expect(screen.getByRole('alertdialog', { name: '确认重构知识结构' })).toBeInTheDocument()
  expect(fetch).not.toHaveBeenCalledWith(expect.stringContaining('/refactor'), expect.anything())
  fireEvent.click(screen.getByRole('button', { name: '确认重构' }))

  expect(await screen.findByText('有效复习需要调整间隔')).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith(
    '/api/knowledge/file/refactor?path=topics%2F%E5%AD%A6%E4%B9%A0%E6%96%B9%E6%B3%95.md',
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
  jobsPayload = [{
    id: 'job-failed', video_title: '失败视频', bvid: 'BVFAILED', status: 'failed', error,
    created_at: '2026-01-01', artifacts: [], parts: [{
      id: 'part-failed', part_index: 1, title: '正片', status: 'failed', artifacts: [],
      stages: [{ stage: 'organize', status: 'failed', error, retries: 0 }],
    }],
  }]

  render(<App />)

  expect(await screen.findByText(error)).toBeInTheDocument()
  expect(screen.getAllByText(error)).toHaveLength(1)
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

test('keeps history jobs compact until expanded', async () => {
  jobsPayload = [{
    id: 'history-detail', video_title: '可展开视频', bvid: 'BVEXPAND', status: 'completed',
    created_at: '2026-01-01', artifacts: [], parts: [{
      id: 'part-expand', part_index: 1, title: '正片', status: 'completed', artifacts: [],
      stages: [{ stage: 'parse', status: 'completed', retries: 0 }],
    }],
  }]
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: '历史任务' }))

  expect(screen.queryByText('解析')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '展开' }))
  expect(screen.getByText('解析')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '收起' })).toBeInTheDocument()
})
