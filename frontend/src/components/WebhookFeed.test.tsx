import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { WebhookCall } from '../api/types'
import WebhookFeed from './WebhookFeed'

const api = vi.hoisted(() => ({ apiGet: vi.fn() }))
vi.mock('../api/client', async (original) => ({ ...(await original<typeof import('../api/client')>()), ...api }))

function call(id: number, overrides: Partial<WebhookCall> = {}): WebhookCall {
  return {
    webhook_call_id: id,
    received_at: '2026-10-16T22:40:00',
    channel: 'webhook',
    outcome: 'stored',
    http_status: 200,
    event_id: `evt_${id}`,
    event: 'login',
    app_user_id: 'u_2b6447a3',
    device_id: 'd_1',
    steps: ['Received', 'Signature verified', 'Payload valid', 'Stored'],
    duration_ms: 4,
    ...overrides,
  }
}

const rejected = call(2, {
  outcome: 'rejected',
  http_status: 401,
  event_id: null,
  event: null,
  app_user_id: null,
  device_id: null,
  steps: ['Received', 'Rejected: Signature does not match'],
})

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  api.apiGet.mockReset()
})
afterEach(() => vi.useRealTimers())

describe('Live webhook feed', () => {
  it('lists calls newest first, shows rejections by their reason, and expands steps', async () => {
    api.apiGet.mockResolvedValue([rejected, call(1)])
    render(<WebhookFeed onNewEvents={() => {}} refreshKey={0} />)

    expect(await screen.findByText('Rejected: Signature does not match')).toBeInTheDocument()
    expect(screen.getByText('evt_1')).toBeInTheDocument()
    expect(api.apiGet).toHaveBeenCalledWith('/webhook_calls?after=0&limit=25')

    const row = screen.getByText('evt_1').closest('button')!
    expect(row).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(row)
    expect(row).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Signature verified')).toBeInTheDocument()
  })

  it('polls for newer calls and refreshes the table when an outside event is stored', async () => {
    const onNewEvents = vi.fn()
    api.apiGet.mockResolvedValueOnce([call(1)]).mockResolvedValueOnce([call(3)]).mockResolvedValue([])
    render(<WebhookFeed onNewEvents={onNewEvents} refreshKey={0} />)
    await screen.findByText('evt_1')
    expect(onNewEvents).not.toHaveBeenCalled() // the first load is history, not news

    await act(() => vi.advanceTimersByTimeAsync(4000))

    expect(await screen.findByText('evt_3')).toBeInTheDocument()
    expect(api.apiGet).toHaveBeenCalledWith('/webhook_calls?after=1&limit=25')
    expect(onNewEvents).toHaveBeenCalledTimes(1)
  })

  it('stops polling while paused', async () => {
    api.apiGet.mockResolvedValue([])
    render(<WebhookFeed onNewEvents={() => {}} refreshKey={0} />)
    await screen.findByText(/No webhook calls yet/)
    await userEvent.click(screen.getByRole('button', { name: 'Pause' }))
    const calls = api.apiGet.mock.calls.length

    await act(() => vi.advanceTimersByTimeAsync(12000))
    expect(api.apiGet.mock.calls.length).toBe(calls)
    expect(screen.getByRole('button', { name: 'Resume' })).toHaveAttribute('aria-pressed', 'true')
  })
})
