import { isRouteErrorResponse, useRouteError } from 'react-router-dom'
import { ErrorState } from '@/components/common/states'

export function RouteErrorPage() {
  const error = useRouteError()
  const normalized = isRouteErrorResponse(error) ? new Error(`${error.status} ${error.statusText}`) : error
  return (
    <div className="mx-auto max-w-xl p-8">
      <ErrorState error={normalized} onRetry={() => window.location.reload()} />
    </div>
  )
}
