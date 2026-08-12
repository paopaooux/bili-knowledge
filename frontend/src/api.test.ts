import { afterEach, expect, test, vi } from 'vitest'
import { api } from './api'

afterEach(() => vi.unstubAllGlobals())

test('accepts an empty 204 response when deleting a job', async () => {
  const fetchMock = vi.fn(async () => new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', fetchMock)

  await expect(api.deleteJob('job-1')).resolves.toBeUndefined()
  expect(fetchMock).toHaveBeenCalledWith('/api/jobs/job-1', expect.objectContaining({ method: 'DELETE' }))
})

test('reads backend and worker health', async () => {
  const fetchMock = vi.fn(async () => new Response(
    JSON.stringify({ ok: true, worker: 'running' }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  ))
  vi.stubGlobal('fetch', fetchMock)

  await expect(api.health()).resolves.toEqual({ ok: true, worker: 'running' })
  expect(fetchMock).toHaveBeenCalledWith('/api/health', expect.anything())
})
