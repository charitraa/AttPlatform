import { Download, FileText, Image as ImageIcon, Lock, Paperclip, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError, apiBlob, saveBlob } from '@/lib/api/client'
import { formatBytes, formatRelative } from '@/lib/format'
import { type Attachment, type Ticket, useAttachments, useUploadAttachment } from '../api'

const ACCEPT = '.png,.jpg,.jpeg,.webp,.gif,.heic,.pdf,.txt,.log,.csv,.docx,.xlsx,.zip'

export function AttachmentsPanel({ ticket }: { ticket: Ticket }) {
  const attachments = useAttachments(ticket.id)
  const upload = useUploadAttachment(ticket.id)
  const input = useRef<HTMLInputElement>(null)
  const [internal, setInternal] = useState(false)
  const canUpload = !ticket.archived_at

  const onFiles = async (files: FileList | null) => {
    for (const file of Array.from(files ?? [])) {
      try {
        await upload.mutateAsync({ file, visibility: internal ? 'internal' : 'public' })
        toast.success(`${file.name} uploaded`)
      } catch (e) {
        const detail = e instanceof ApiError && e.details && typeof e.details === 'object'
          ? Object.values(e.details as Record<string, string[]>).flat()[0] : null
        toast.error(`${file.name}: ${detail ?? (e instanceof Error ? e.message : 'upload failed')}`)
      }
    }
    if (input.current) input.current.value = ''
  }

  const download = async (a: Attachment) => {
    try {
      saveBlob(await apiBlob(a.download_url), a.original_name)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Download failed.')
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2"><Paperclip className="size-4" /> Attachments</CardTitle>
        {canUpload && (
          <Button size="sm" variant="outline" onClick={() => input.current?.click()} disabled={upload.isPending}>
            <Upload /> {upload.isPending ? 'Uploading…' : 'Upload'}
          </Button>
        )}
        <input ref={input} type="file" multiple accept={ACCEPT} className="sr-only" aria-label="Upload attachment"
          onChange={(e) => void onFiles(e.target.files)} />
      </CardHeader>
      <CardContent className="space-y-3">
        {canUpload && ticket.capabilities.internal_notes && (
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input type="checkbox" className="accent-primary" checked={internal} onChange={(e) => setInternal(e.target.checked)} />
            Upload as internal (hidden from the customer)
          </label>
        )}
        {attachments.isPending ? <Skeleton className="h-10" /> : attachments.data?.length ? (
          <ul className="divide-y">
            {attachments.data.map((a) => {
              const Icon = a.content_type.startsWith('image/') ? ImageIcon : FileText
              return (
                <li key={a.id} className="flex items-center gap-3 py-2">
                  <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{a.original_name}</div>
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      {formatBytes(a.size_bytes)} · {a.uploaded_by?.full_name ?? 'Unknown'} · {formatRelative(a.created_at)}
                      {a.visibility === 'internal' && <span className="inline-flex items-center gap-0.5 text-warning"><Lock className="size-3" /> internal</span>}
                    </div>
                  </div>
                  <Button size="icon-sm" variant="ghost" aria-label={`Download ${a.original_name}`} onClick={() => download(a)}><Download /></Button>
                </li>
              )
            })}
          </ul>
        ) : <p className="text-sm text-muted-foreground">No files yet. Photos, PDFs, logs and Office documents up to 20 MB.</p>}
      </CardContent>
    </Card>
  )
}
