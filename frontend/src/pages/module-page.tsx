import { Construction } from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/common/page-header'
import { EmptyState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import type { NavItem } from '@/config/navigation'

/**
 * Route target for modules not yet delivered. It says so plainly instead of
 * rendering mock data. Each phase replaces these with real feature pages.
 */
export function ModulePage({ item }: { item: NavItem }) {
  return (
    <div className="space-y-6">
      <PageHeader title={item.label} description={item.summary} />
      <EmptyState
        icon={Construction}
        title={`${item.label} ships in Phase ${item.phase}`}
        description="This module isn't implemented yet. No placeholder data is shown, so nothing here can be mistaken for real figures."
        action={<Button variant="outline" size="sm" render={<Link to="/system" />}>View system status</Button>}
      />
    </div>
  )
}
