import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import App from './App'

vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
  const url = String(input)
  const payload = url.endsWith('/api/jobs') ? [] : url.endsWith('/api/knowledge/profiles') ? [{
    id: 'profile-1', name: '个人成长与学习', mode: 'guided', scope: '学习与成长知识',
    preferred_topics: [{ name: '学习方法', path: '个人成长/学习方法.md', description: '学习方法' }],
    rules: { ignore_out_of_scope: true, merge_similar: true }, is_active: true,
    version: 1, created_at: '2026-01-01', updated_at: '2026-01-01',
  }] : { stt_model: 'whisper-1', llm_model: 'test-model', knowledge_base_dir: '/tmp/kb' }
  return new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } })
}))

test('opens profile management in a separate modal', async () => {
  render(<App />)
  expect(screen.getByText('让视频的价值，')).toBeInTheDocument()
  expect(screen.getByLabelText('Bilibili 视频链接')).toBeInTheDocument()
  expect(await screen.findByText('test-model')).toBeInTheDocument()
  expect(screen.queryByRole('dialog', { name: '知识库 Profile 设置' })).not.toBeInTheDocument()
  fireEvent.click(await screen.findByRole('button', { name: '知识库设置' }))
  expect(screen.getByRole('dialog', { name: '知识库 Profile 设置' })).toBeInTheDocument()
  expect(await screen.findByDisplayValue('个人成长与学习')).toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: '主题名称' })).toHaveValue('学习方法')
  fireEvent.click(screen.getByRole('tab', { name: '使用说明' }))
  expect(screen.getByText('Profile 是什么？')).toBeInTheDocument()
  expect(screen.getByText('如何添加推荐主题？')).toBeInTheDocument()
  expect(screen.getByText('完整例子：个人成长知识库')).toBeInTheDocument()
  expect(screen.getByText(/识别为“学习方法”/)).toBeInTheDocument()
})
