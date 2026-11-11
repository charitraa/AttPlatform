import { Link } from 'react-router-dom'
import { EmptyState } from '@/components/common/states'
import { Button } from '@/components/ui/button'

export function NotFoundPage() {
  return (
    <EmptyState
      className="mt-12"
      title="Page not found"
      description="The page you're looking for doesn't exist or has moved."
      action={<Button size="sm" render={<Link to="/" />}>Back to dashboard</Button>}
    />
  )
}
