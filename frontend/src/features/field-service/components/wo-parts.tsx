import { Camera, Check, Download, FileText, Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { NativeSelect } from '@/components/forms/native-select'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { apiBlob, saveBlob } from '@/lib/api/client'
import { firstErrorMessage } from '@/lib/forms'
import { formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { type Evidence, useEvidence, useUploadEvidence, WO_STATUS_LABEL, type WOStatus } from '../api'

const STATUS_STYLE: Record<WOStatus, string> = {
  created: 'border-border text-muted-foreground',
  assigned: 'border-primary/40 text-primary',
  accepted: 'border-primary/40 text-primary',
  en_route: 'border-series-1/50 bg-series-1/10',
  on_site: 'border-series-1/50 bg-series-1/10',
  in_progress: 'border-series-1/50 bg-series-1/10',
  completed: 'border-success/50 text-success',
  cancelled: 'border-border text-muted-foreground line-through',
}

export function WOStatusBadge({ status, className }: { status: WOStatus; className?: string }) {
  return <Badge variant="outline" className={cn('whitespace-nowrap', STATUS_STYLE[status], className)}>{WO_STATUS_LABEL[status]}</Badge>
}

const FLOW: WOStatus[] = ['created', 'assigned', 'accepted', 'en_route', 'on_site', 'in_progress', 'completed']

/** Progress through the field workflow; text labels carry the meaning, colour only reinforces. */
export function WOStepper({ status }: { status: WOStatus }) {
  if (status === 'cancelled') return <p className="text-sm text-muted-foreground">This work order was cancelled.</p>
  const current = FLOW.indexOf(status)
  return (
    <ol className="flex flex-wrap gap-x-1 gap-y-2 text-xs" aria-label="Work order progress">
      {FLOW.map((s, i) => (
        <li key={s} className="flex items-center gap-1" aria-current={i === current ? 'step' : undefined}>
          <span className={cn('flex size-5 items-center justify-center rounded-full border text-[10px]',
            i < current && 'border-primary bg-primary text-primary-foreground',
            i === current && 'border-primary text-primary ring-2 ring-primary/20')}>
            {i < current ? <Check className="size-3" /> : i + 1}
          </span>
          <span className={cn(i === current ? 'font-medium text-foreground' : 'text-muted-foreground')}>{WO_STATUS_LABEL[s]}</span>
          {i < FLOW.length - 1 && <span className="mx-1 h-px w-3 bg-border" aria-hidden />}
        </li>
      ))}
    </ol>
  )
}

const KIND_LABEL: Record<Evidence['kind'], string> = {
  before_photo: 'Before', after_photo: 'After', document: 'Document', signature: 'Signature', other: 'Other',
}

function Thumb({ ev }: { ev: Evidence }) {
  const [src, setSrc] = useState<string | null>(null)
  const isImage = ev.content_type.startsWith('image/') && ev.content_type !== 'image/heic'
  useEffect(() => {
    if (!isImage) return
    let url: string | null = null
    let cancelled = false
    // Files require auth, so fetch them as blobs rather than pointing <img> at the API.
    apiBlob(`${ev.download_url}?inline=1`).then((blob) => {
      if (cancelled) return
      url = URL.createObjectURL(blob)
      setSrc(url)
    }).catch(() => undefined)
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [ev.download_url, isImage])
  return (
    <div className="flex aspect-square items-center justify-center overflow-hidden rounded-md bg-muted">
      {src ? <img src={src} alt={ev.caption || ev.original_name} className="size-full object-cover" /> : <FileText className="size-6 text-muted-foreground" aria-hidden />}
    </div>
  )
}

export function EvidenceGallery({ workOrderId, canUpload, defaultKind = 'after_photo' }: {
  workOrderId: string; canUpload: boolean; defaultKind?: Evidence['kind']
}) {
  const evidence = useEvidence(workOrderId)
  const upload = useUploadEvidence(workOrderId)
  const [kind, setKind] = useState<Evidence['kind']>(defaultKind)
  const fileInput = useRef<HTMLInputElement>(null)
  const cameraInput = useRef<HTMLInputElement>(null)
  useEffect(() => setKind(defaultKind), [defaultKind])

  const onFiles = async (files: FileList | null) => {
    for (const file of Array.from(files ?? [])) {
      try {
        await upload.mutateAsync({ file, kind })
        toast.success(`${KIND_LABEL[kind]} ${kind.endsWith('photo') ? 'photo' : 'file'} added`)
      } catch (e) {
        toast.error(`${file.name}: ${firstErrorMessage(e)}`)
      }
    }
    if (fileInput.current) fileInput.current.value = ''
    if (cameraInput.current) cameraInput.current.value = ''
  }

  const items = evidence.data ?? []
  return (
    <div className="space-y-3">
      {canUpload && (
        <div className="flex flex-wrap items-center gap-2">
          <NativeSelect aria-label="Evidence type" className="w-36" value={kind} onChange={(e) => setKind(e.target.value as Evidence['kind'])}>
            {Object.entries(KIND_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </NativeSelect>
          <Button size="sm" variant="outline" onClick={() => cameraInput.current?.click()} disabled={upload.isPending}><Camera /> Take photo</Button>
          <Button size="sm" variant="outline" onClick={() => fileInput.current?.click()} disabled={upload.isPending}><Upload /> {upload.isPending ? 'Uploading…' : 'Upload file'}</Button>
          {/* capture opens the rear camera on phones; falls back to a file picker on desktops */}
          <input ref={cameraInput} type="file" accept="image/*" capture="environment" className="sr-only" aria-label="Take photo" onChange={(e) => void onFiles(e.target.files)} />
          <input ref={fileInput} type="file" multiple accept="image/*,.pdf,.txt,.csv,.docx,.xlsx,.zip" className="sr-only" aria-label="Upload evidence" onChange={(e) => void onFiles(e.target.files)} />
        </div>
      )}
      {items.length === 0 ? <p className="text-sm text-muted-foreground">No photos or documents yet.</p> : (
        <ul className="grid grid-cols-3 gap-3 sm:grid-cols-4">
          {items.map((ev) => (
            <li key={ev.id} className="space-y-1">
              <Thumb ev={ev} />
              <div className="flex items-center justify-between gap-1">
                <span className="truncate text-xs"><span className="font-medium">{KIND_LABEL[ev.kind]}</span> · {formatRelative(ev.created_at)}</span>
                <button type="button" className="rounded p-0.5 text-muted-foreground hover:text-foreground" aria-label={`Download ${ev.original_name}`}
                  onClick={async () => saveBlob(await apiBlob(ev.download_url), ev.original_name)}>
                  <Download className="size-3.5" />
                </button>
              </div>
              {ev.caption && <p className="truncate text-xs text-muted-foreground">{ev.caption}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
