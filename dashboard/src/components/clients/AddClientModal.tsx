import { useState } from 'react'
import { clientsApi } from '@/api/clients'
import clsx from 'clsx'

interface Props {
  onClose: () => void
  onCreated: () => void
}

export function AddClientModal({ onClose, onCreated }: Props) {
  const [form, setForm] = useState({
    display_name: '',
    callsign: '',
    email: '',
    phone: '',
    notes: '',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  function set(field: keyof typeof form) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((f) => ({ ...f, [field]: e.target.value }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.display_name.trim()) return
    setError('')
    setLoading(true)
    try {
      await clientsApi.create({
        display_name: form.display_name.trim(),
        callsign:     form.callsign.trim() || undefined,
        email:        form.email.trim()    || undefined,
        phone:        form.phone.trim()    || undefined,
        notes:        form.notes.trim()    || undefined,
      })
      onCreated()
    } catch (err) {
      setError('Failed to create client. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    // Backdrop
    <div
      className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-surface-raised border border-surface-border rounded-2xl w-full max-w-md shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-surface-border">
          <h2 className="font-semibold text-base">Add Client</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl leading-none">×</button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          {/* Name — required */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Full name <span className="text-accent-red">*</span>
            </label>
            <input
              value={form.display_name}
              onChange={set('display_name')}
              placeholder="Alice Smith"
              className={inputCls}
              autoFocus
            />
          </div>

          {/* Callsign — optional, auto-generated if blank */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Callsign
              <span className="text-gray-600 ml-1">(auto-generated if left blank)</span>
            </label>
            <input
              value={form.callsign}
              onChange={set('callsign')}
              placeholder="AliceS"
              className={inputCls}
            />
          </div>

          {/* Contact — side by side */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Email</label>
              <input
                type="email"
                value={form.email}
                onChange={set('email')}
                placeholder="alice@email.com"
                className={inputCls}
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Phone</label>
              <input
                type="tel"
                value={form.phone}
                onChange={set('phone')}
                placeholder="+44 7700 900000"
                className={inputCls}
              />
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">Notes</label>
            <textarea
              value={form.notes}
              onChange={set('notes')}
              placeholder="Medical info, experience level, emergency contact…"
              rows={2}
              className={clsx(inputCls, 'resize-none')}
            />
          </div>

          {error && <p className="text-accent-red text-sm">{error}</p>}

          {/* Actions */}
          <div className="flex gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 bg-surface border border-surface-border rounded-lg py-2.5 text-sm font-medium hover:bg-surface-border transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading || !form.display_name.trim()}
              className="flex-1 bg-accent hover:bg-blue-500 disabled:opacity-40 rounded-lg py-2.5 text-sm font-medium transition-colors"
            >
              {loading ? 'Adding…' : 'Add Client'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

const inputCls =
  'w-full bg-surface border border-surface-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-accent placeholder:text-gray-600'
