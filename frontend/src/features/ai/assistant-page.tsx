import { BookOpen, FileText, Loader2, Pencil, Plus, Search, Send, Sparkles, Ticket as TicketIcon } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Field } from '@/components/forms/field'
import { FormError } from '@/components/forms/form-error'
import { NativeSelect } from '@/components/forms/native-select'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { type Article, useArticles, useMoveArticle, useSaveArticle } from '@/features/knowledge/api'
import { useCategories } from '@/features/tickets/api'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { formatRelative } from '@/lib/format'
import { firstErrorMessage } from '@/lib/forms'
import { useCan } from '@/stores/auth'
import { type Analysis, useAsk, useAssistantHistory } from './api'
import { Confidence, DemoBadge } from './components/ai-panel'

type Source = { id: string; kind: 'article' | 'ticket'; object_id: string; title: string }

function AnswerCard({ a }: { a: Analysis }) {
  const question = String(a.input.question ?? '')
  const busy = a.status === 'pending' || a.status === 'running'
  const out = a.output as { answer: string; steps: string[]; sources: Source[]; confidence: number } | null
  return (
    <Card>
      <CardHeader className="space-y-1">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-base">{question}</CardTitle>
          {a.is_mock && <DemoBadge />}
        </div>
        <p className="text-xs text-muted-foreground">{formatRelative(a.created_at)}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        {busy && <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Searching the knowledge base and resolved tickets…</p>}
        {a.status === 'failed' && <p role="alert" className="text-sm text-destructive">Couldn't answer: {a.error}</p>}
        {out && (
          <>
            <p className="text-sm whitespace-pre-wrap">{out.answer}</p>
            {out.steps.length > 0 && <ol className="ml-5 list-decimal space-y-1 text-sm">{out.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>}
            <div className="flex flex-wrap items-center gap-3 border-t pt-3">
              <Confidence value={a.confidence} />
              {out.sources.length > 0 ? (
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  <span className="text-muted-foreground">Sources:</span>
                  {out.sources.map((s) => (
                    s.kind === 'ticket'
                      ? <Link key={s.id} to={`/tickets/${s.object_id}`} className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 hover:bg-muted"><TicketIcon className="size-3" /> {s.title}</Link>
                      : <span key={s.id} className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5"><BookOpen className="size-3" /> {s.title}</span>
                  ))}
                </div>
              ) : <span className="text-xs text-muted-foreground">No matching sources.</span>}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function AskTab() {
  const ask = useAsk()
  const history = useAssistantHistory()
  const [question, setQuestion] = useState('')
  const submit = async () => {
    if (question.trim().length < 3) return
    try {
      await ask.mutateAsync(question.trim())
      setQuestion('')
    } catch (e) {
      toast.error(firstErrorMessage(e))
    }
  }
  return (
    <div className="space-y-6">
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void submit() }}>
        <Input aria-label="Question" placeholder="e.g. How do we fix a cold room compressor that short-cycles?" value={question}
          onChange={(e) => setQuestion(e.target.value)} maxLength={1000} />
        <Button type="submit" disabled={question.trim().length < 3 || ask.isPending}><Send /> Ask</Button>
      </form>
      <p className="text-xs text-muted-foreground">Answers draw only on published knowledge articles and resolved tickets in your organization, and always list their sources.</p>
      {history.isPending ? <Skeleton className="h-40" /> : history.isError ? <ErrorState error={history.error} onRetry={() => history.refetch()} /> :
        history.data.length === 0 ? <EmptyState icon={Sparkles} title="Ask your first question" description="Try a symptom, an error message or an asset model." /> : (
          <div className="space-y-4">{history.data.map((a) => <AnswerCard key={a.id} a={a} />)}</div>
        )}
    </div>
  )
}

const STATUS_STYLE: Record<Article['status'], string> = {
  draft: 'text-muted-foreground', in_review: 'border-warning/50 text-warning', published: 'border-success/50 text-success', archived: 'text-muted-foreground',
}
const STATUS_LABEL: Record<Article['status'], string> = { draft: 'Draft', in_review: 'In review', published: 'Published', archived: 'Archived' }

function ArticleDialog({ article, onClose }: { article?: Article; onClose: () => void }) {
  const save = useSaveArticle(article?.id)
  const categories = useCategories()
  const [form, setForm] = useState({
    title: article?.title ?? '', summary: article?.summary ?? '', body: article?.body ?? '',
    category: article?.category ?? '', tags: article?.tags.join(', ') ?? '',
  })
  const [error, setError] = useState<string | null>(null)
  const submit = async () => {
    try {
      await save.mutateAsync({ ...form, category: form.category || null, tags: form.tags.split(',').map((t) => t.trim()).filter(Boolean) })
      toast.success(article ? 'Article saved' : 'Draft created')
      onClose()
    } catch (e) {
      setError(firstErrorMessage(e))
    }
  }
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader><DialogTitle>{article ? 'Edit article' : 'New article'}</DialogTitle></DialogHeader>
        <div className="grid gap-4">
          <FormError message={error} />
          <Field label="Title"><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} autoFocus /></Field>
          <Field label="Summary"><Input value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} maxLength={500} /></Field>
          <Field label="Body" description="Markdown: Problem, Cause, Resolution."><Textarea rows={12} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Category">
              <NativeSelect value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                <option value="">None</option>
                {categories.data?.map((c) => <option key={c.id} value={c.id}>{c.full_name}</option>)}
              </NativeSelect>
            </Field>
            <Field label="Tags"><Input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} /></Field>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={!form.title.trim() || !form.body.trim() || save.isPending}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function KnowledgeTab() {
  const canManage = useCan('knowledge.manage')
  const [status, setStatus] = useState(canManage ? 'draft' : '')
  const [search, setSearch] = useState('')
  const articles = useArticles({ status, search: useDebouncedValue(search) })
  const move = useMoveArticle()
  const [editing, setEditing] = useState<Article | 'new' | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  const doMove = async (a: Article, action: 'submit' | 'publish' | 'return-to-draft' | 'archive') => {
    try {
      await move.mutateAsync({ id: a.id, action })
      toast.success({ submit: 'Sent for review', publish: 'Published', 'return-to-draft': 'Returned to draft', archive: 'Archived' }[action])
    } catch (e) {
      toast.error(firstErrorMessage(e))
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" aria-label="Search articles" placeholder="Search articles" className="pl-8" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        {canManage && (
          <NativeSelect aria-label="Article status" className="w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="draft">Drafts</option><option value="in_review">In review</option><option value="published">Published</option>
            <option value="archived">Archived</option><option value="">All</option>
          </NativeSelect>
        )}
        {canManage && <Button className="ml-auto" size="sm" onClick={() => setEditing('new')}><Plus /> New article</Button>}
      </div>
      {articles.isPending ? <Skeleton className="h-32" /> : articles.isError ? <ErrorState error={articles.error} onRetry={() => articles.refetch()} /> :
        articles.data.count === 0 ? (
          <EmptyState icon={FileText} title={status === 'draft' ? 'No drafts waiting for review' : 'No articles found'}
            description={status === 'draft' ? 'Drafts appear here automatically when tickets with resolution notes are closed.' : undefined} />
        ) : (
          <ul className="space-y-3">
            {articles.data.results.map((a) => (
              <li key={a.id} className="rounded-lg border p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <button type="button" className="text-left font-medium hover:underline" onClick={() => setOpen(open === a.id ? null : a.id)} aria-expanded={open === a.id}>{a.title}</button>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                      <Badge variant="outline" className={STATUS_STYLE[a.status]}>{STATUS_LABEL[a.status]}</Badge>
                      {a.source === 'ai_extracted' && <Badge variant="outline"><Sparkles className="size-3" /> From a resolved ticket</Badge>}
                      {a.source_ticket && <Link to={`/tickets/${a.source_ticket.id}`} className="hover:underline">{a.source_ticket.reference}</Link>}
                      {a.category_name && <span>· {a.category_name}</span>}
                      <span>· updated {formatRelative(a.updated_at)}</span>
                    </div>
                  </div>
                  {canManage && (
                    <div className="flex flex-wrap gap-1.5">
                      <Button size="xs" variant="ghost" onClick={() => setEditing(a)} aria-label={`Edit ${a.title}`}><Pencil /></Button>
                      {a.status === 'draft' && <Button size="xs" variant="outline" onClick={() => doMove(a, 'submit')}>Send for review</Button>}
                      {(a.status === 'draft' || a.status === 'in_review') && <Button size="xs" onClick={() => doMove(a, 'publish')}>Publish</Button>}
                      {a.status === 'published' && <Button size="xs" variant="outline" onClick={() => doMove(a, 'return-to-draft')}>Unpublish</Button>}
                      {a.status !== 'archived' && <Button size="xs" variant="ghost" onClick={() => doMove(a, 'archive')}>Archive</Button>}
                    </div>
                  )}
                </div>
                {a.summary && <p className="mt-2 text-sm text-muted-foreground">{a.summary}</p>}
                {open === a.id && <pre className="mt-3 rounded-md bg-muted p-3 font-sans text-sm whitespace-pre-wrap">{a.body}</pre>}
              </li>
            ))}
          </ul>
        )}
      {editing && <ArticleDialog article={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

export function AssistantPage() {
  const canRead = useCan('knowledge.view')
  return (
    <div className="space-y-6">
      <PageHeader title="AI Assistant" description="Ask about troubleshooting procedures, and curate the knowledge base the assistant learns from." />
      <Tabs defaultValue="ask">
        <TabsList>
          <TabsTrigger value="ask">Ask</TabsTrigger>
          {canRead && <TabsTrigger value="knowledge">Knowledge base</TabsTrigger>}
        </TabsList>
        <TabsContent value="ask" className="pt-4"><AskTab /></TabsContent>
        {canRead && <TabsContent value="knowledge" className="pt-4"><KnowledgeTab /></TabsContent>}
      </Tabs>
    </div>
  )
}
