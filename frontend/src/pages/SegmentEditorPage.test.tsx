import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SegmentSchema } from '../api/types'
import SegmentEditorPage from './SegmentEditorPage'

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiSend: vi.fn() }))
vi.mock('../api/client', async (original) => ({ ...(await original<typeof import('../api/client')>()), ...api }))

const SCHEMA: SegmentSchema = {
  today: '2026-09-28',
  fields: {
    acquisition_source: {
      type: 'string',
      label: 'Acquisition source',
      description: 'Where they signed up from',
      category: 'Subscriber',
      operators: ['equals', 'not_equals', 'in', 'not_in', 'is_empty', 'is_not_empty'],
      values: ['Facebook', 'Instagram'],
    },
    last_open_date: {
      type: 'date',
      label: 'Last email open',
      description: 'Most recent newsletter open',
      category: 'Subscriber',
      operators: ['before', 'after', 'on', 'within_last_days', 'not_within_last_days', 'is_empty', 'is_not_empty'],
    },
  },
}

function renderEditor() {
  return render(
    <MemoryRouter initialEntries={['/segments/new']}>
      <Routes>
        <Route path="/segments/new" element={<SegmentEditorPage />} />
        <Route path="/segments/:slug" element={<p>Saved segment page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  api.apiGet.mockReset().mockResolvedValue(SCHEMA)
  api.apiSend.mockReset().mockImplementation((_method: string, path: string, body: unknown) => {
    if (path === '/segments/preview') return Promise.resolve({ member_count: 59, summary: 'Acquisition source is Instagram' })
    return Promise.resolve({ ...(body as object), slug: 'instagram-readers' })
  })
})

describe('Segment builder', () => {
  it('starts with everyone and counts members live as rules are added', async () => {
    renderEditor()
    expect(await screen.findByText(/No rules yet/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '+ Add rule' }))
    await userEvent.selectOptions(screen.getByLabelText('Value'), 'Instagram')

    expect(await screen.findByText('59 people')).toBeInTheDocument()
    const previews = api.apiSend.mock.calls.filter(([, path]) => path === '/segments/preview')
    expect(previews.at(-1)![2]).toEqual({
      match: 'all',
      filters: [{ field: 'acquisition_source', operator: 'equals', value: 'Instagram' }],
    })
  })

  it('resets the value when the field or condition changes shape, and blocks saving incomplete rules', async () => {
    renderEditor()
    await userEvent.click(await screen.findByRole('button', { name: '+ Add rule' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Instagram readers')

    await userEvent.selectOptions(screen.getByLabelText('Condition'), 'in') // a list now: nothing picked yet
    expect(screen.getByText('Finish each rule to see a count.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save segment' })).toBeDisabled()

    await userEvent.selectOptions(screen.getByLabelText('Field'), 'last_open_date')
    expect(screen.getByLabelText('Condition')).toHaveValue('before')
    await userEvent.selectOptions(screen.getByLabelText('Condition'), 'within_last_days')
    expect(screen.getByLabelText('Days')).toHaveValue(30)
  })

  it('saves a clean definition and opens the new segment', async () => {
    renderEditor()
    await userEvent.click(await screen.findByRole('button', { name: '+ Add rule' }))
    await userEvent.type(screen.getByLabelText('Name'), '  Instagram readers ')
    await userEvent.selectOptions(screen.getByLabelText('Value'), 'Instagram')
    await screen.findByText('59 people')

    await userEvent.click(screen.getByRole('button', { name: 'Save segment' }))

    expect(await screen.findByText('Saved segment page')).toBeInTheDocument()
    const save = api.apiSend.mock.calls.find(([, path]) => path === '/segments')!
    expect(save[0]).toBe('POST')
    expect(save[2]).toEqual({
      name: 'Instagram readers',
      description: '',
      group: 'subscriber',
      definition: { match: 'all', filters: [{ field: 'acquisition_source', operator: 'equals', value: 'Instagram' }] },
    })
  })

  it('shows a server error instead of navigating', async () => {
    api.apiSend.mockImplementation((_m: string, path: string) =>
      path === '/segments' ? Promise.reject(new Error('A segment with that name already exists')) : Promise.resolve({ member_count: 1, summary: '' }),
    )
    renderEditor()
    await userEvent.type(await screen.findByLabelText('Name'), 'Everyone')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save segment' })).toBeEnabled())

    await userEvent.click(screen.getByRole('button', { name: 'Save segment' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('A segment with that name already exists')
  })
})
