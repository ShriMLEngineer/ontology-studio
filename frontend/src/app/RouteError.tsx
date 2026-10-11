import { isRouteErrorResponse, Link, useRouteError } from 'react-router'

import { ErrorState } from '@/components/common/states'
import { Button } from '@/components/ui/button'

export function RouteError({ forceNotFound = false }: { forceNotFound?: boolean }) {
  const error = useRouteError()
  const notFound = forceNotFound || (isRouteErrorResponse(error) && error.status === 404)
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
      <ErrorState
        className="max-w-lg flex-none"
        title={notFound ? 'Page not found' : 'Unexpected application error'}
        error={notFound ? new Error('The requested page does not exist.') : error}
      />
      <Button asChild variant="outline">
        <Link to="/">Back to projects</Link>
      </Button>
    </div>
  )
}
