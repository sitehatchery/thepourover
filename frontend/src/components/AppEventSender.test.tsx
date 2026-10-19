import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AppEventSender from './AppEventSender'

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiSend: vi.fn() }))
vi.mock('../api/client', async (original) => ({ ...(await original<typeof import('../api/client')>()), ...api }))

beforeEach(() => {
  api.apiGet.mockReset().mockResolvedValue([])
  api.apiSend.mockReset()
})

const send = () => screen.getByRole('button', { name: 'Send through webhook' })

describe('App Events form validation', () => {
  it('blocks ids with characters the webhook would reject', async () => {
    render(<AppEventSender onSent={() => {}} />)
    const eventId = screen.getByLabelText('Event ID')

    await userEvent.clear(eventId)
    await userEvent.type(eventId, 'evt 1; drop')
    expect(screen.getByText('Event ID can use letters, numbers, _ and - only.')).toBeInTheDocument()
    expect(send()).toBeDisabled()

    await userEvent.clear(eventId)
    await userEvent.type(eventId, 'evt_ok-1')
    expect(send()).toBeEnabled()
  })

  it('requires a device and a value for every property row', async () => {
    render(<AppEventSender onSent={() => {}} />)

    await userEvent.clear(screen.getByLabelText(/Device ID/))
    expect(screen.getByText(/Device ID is required/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Device ID/), 'd_1')

    await userEvent.click(screen.getByRole('button', { name: '+ Add property' }))
    expect(screen.getByText('Fill in or remove empty property rows.')).toBeInTheDocument()
    expect(send()).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Property value'), 'big-story')
    expect(send()).toBeEnabled()
  })

  it('sends a blank user as anonymous, in UTC, and shows each webhook step', async () => {
    const onSent = vi.fn()
    api.apiSend.mockResolvedValue({
      status: 'stored',
      event_id: 'evt_test',
      app_user_id: null,
      attached_events: 0,
      placeholder_created: false,
      steps: ['Received', 'Signature verified', 'Payload valid', 'Stored'],
    })
    render(<AppEventSender onSent={onSent} />)
    await userEvent.clear(screen.getByLabelText('Event ID'))
    await userEvent.type(screen.getByLabelText('Event ID'), 'evt_test')
    await userEvent.click(screen.getByRole('button', { name: '+ Add property' }))
    await userEvent.type(screen.getByLabelText('Property value'), 'big-story')

    await userEvent.click(send())

    await waitFor(() => expect(onSent).toHaveBeenCalled())
    const [method, path, body] = api.apiSend.mock.calls[0]
    expect([method, path]).toEqual(['POST', '/app_events/send'])
    expect(body).toMatchObject({ event_id: 'evt_test', event: 'app_open', user_id: null, properties: { story: 'big-story' } })
    expect(body.timestamp).toMatch(/^2026-09-28T\d\d:\d\d:\d\dZ$/)
    expect(screen.getByText('Signature verified')).toBeInTheDocument()
    expect(screen.getByLabelText('Event ID')).not.toHaveValue('evt_test') // a fresh id for the next event
  })
})
