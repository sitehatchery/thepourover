import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import DataTable, { type Column } from './DataTable'
import Pagination from './Pagination'

type Row = { id: string; email: string }
const COLUMNS: Column<Row>[] = [
  { key: 'id', label: 'ID', render: (r) => r.id },
  { key: 'email', label: 'Email', sortable: true, render: (r) => r.email },
]
const ROWS = [
  { id: '1', email: 'a@example.com' },
  { id: '2', email: 'b@example.com' },
]

describe('DataTable sorting', () => {
  it('marks the sorted column and sorts on header click', async () => {
    const onSort = vi.fn()
    render(<DataTable caption="People" columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} sort="email" order="asc" onSort={onSort} />)

    expect(screen.getByRole('columnheader', { name: /email/i })).toHaveAttribute('aria-sort', 'ascending')
    expect(screen.getByRole('columnheader', { name: 'ID' })).not.toHaveAttribute('aria-sort')
    expect(screen.queryByRole('button', { name: 'ID' })).toBeNull() // not sortable

    await userEvent.click(screen.getByRole('button', { name: /email/i }))
    expect(onSort).toHaveBeenCalledWith('email')
    expect(screen.getAllByRole('row')).toHaveLength(3)
  })
})

describe('Pagination', () => {
  it('is hidden when everything fits on one page', () => {
    const { container } = render(<Pagination page={1} pageSize={40} total={40} onPage={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the range and moves between pages', async () => {
    const onPage = vi.fn()
    render(<Pagination page={2} pageSize={40} total={2900} onPage={onPage} />)

    expect(screen.getByText('41–80 of 2,900')).toBeInTheDocument()
    expect(screen.getByText('Page 2 of 73')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    await userEvent.click(screen.getByRole('button', { name: 'Last page' }))
    await userEvent.click(screen.getByRole('button', { name: 'First page' }))
    expect(onPage.mock.calls).toEqual([[3], [73], [1]])
  })

  it('disables the buttons at either end', () => {
    render(<Pagination page={73} pageSize={40} total={2900} onPage={() => {}} />)
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Previous' })).toBeEnabled()
  })
})
