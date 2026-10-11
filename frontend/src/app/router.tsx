import { createBrowserRouter, Navigate } from 'react-router'

import { RouteError } from '@/app/RouteError'
import { AppShell } from '@/components/layout/AppShell'
import { KnowledgeGraphStudioPage } from '@/features/kg/KnowledgeGraphStudioPage'
import { OntologyStudioPage } from '@/features/ontology/OntologyStudioPage'
import { RootRedirect } from '@/features/projects/RootRedirect'
import { WorkspacePage } from '@/features/workspace/WorkspacePage'

export const router = createBrowserRouter([
  { path: '/', element: <RootRedirect />, errorElement: <RouteError /> },
  {
    path: '/projects/:projectId',
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Navigate to="workspace" replace /> },
      { path: 'workspace', element: <WorkspacePage /> },
      { path: 'ontology', element: <OntologyStudioPage /> },
      { path: 'knowledge-graph', element: <KnowledgeGraphStudioPage /> },
    ],
  },
  { path: '*', element: <RouteError forceNotFound /> },
])
