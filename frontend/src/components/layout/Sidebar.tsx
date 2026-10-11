import { useState } from 'react'
import { ChevronsLeft, ChevronsRight, LayoutDashboard, Network, Waypoints } from 'lucide-react'
import { NavLink } from 'react-router'
import { cn } from 'cn'

import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

const COLLAPSED_KEY = 'ols.sidebarCollapsed'

const NAV_ITEMS = [
  { path: 'workspace', label: 'Project Workspace', icon: LayoutDashboard },
  { path: 'ontology', label: 'Ontology Studio', icon: Network },
  { path: 'knowledge-graph', label: 'Knowledge Graph Studio', icon: Waypoints },
] as const

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === 'true'
  } catch {
    return false
  }
}

export function Sidebar({ projectId }: { projectId: string }) {
  const [collapsed, setCollapsed] = useState(readCollapsed)

  const toggle = () => {
    setCollapsed((value) => {
      try {
        localStorage.setItem(COLLAPSED_KEY, String(!value))
      } catch {
        /* non-critical */
      }
      return !value
    })
  }

  return (
    <nav
      aria-label="Primary"
      className={cn(
        'flex h-full shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground transition-[width] duration-200',
        collapsed ? 'w-16' : 'w-64',
      )}
    >
      <div className={cn('flex h-14 items-center gap-2.5 border-b px-4', collapsed && 'justify-center px-0')}>
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Network className="size-4" />
        </div>
        {!collapsed && (
          <div className="min-w-0 leading-tight">
            <p className="truncate text-sm font-semibold">Ontology Lifecycle</p>
            <p className="truncate text-xs text-muted-foreground">Studio</p>
          </div>
        )}
      </div>

      <ul className="flex flex-1 flex-col gap-1 p-2">
        {NAV_ITEMS.map(({ path, label, icon: Icon }) => {
          const link = (
            <NavLink
              to={`/projects/${projectId}/${path}`}
              className={({ isActive }) =>
                cn(
                  'flex h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
                  isActive && 'bg-sidebar-accent text-sidebar-accent-foreground',
                  collapsed && 'justify-center px-0',
                )
              }
            >
              <Icon className="size-4 shrink-0" />
              {!collapsed && <span className="truncate">{label}</span>}
            </NavLink>
          )
          return (
            <li key={path}>
              {collapsed ? (
                <Tooltip>
                  <TooltipTrigger asChild>{link}</TooltipTrigger>
                  <TooltipContent side="right">{label}</TooltipContent>
                </Tooltip>
              ) : (
                link
              )}
            </li>
          )
        })}
      </ul>

      <div className={cn('border-t p-2', collapsed && 'flex justify-center')}>
        <Button
          variant="ghost"
          size={collapsed ? 'icon' : 'sm'}
          className={cn(!collapsed && 'w-full justify-start text-muted-foreground')}
          onClick={toggle}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronsRight /> : <ChevronsLeft />}
          {!collapsed && 'Collapse'}
        </Button>
      </div>
    </nav>
  )
}
