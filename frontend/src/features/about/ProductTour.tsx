import { useState } from 'react'
import { ArrowRight, ArrowUpRight } from 'lucide-react'
import { Link } from 'react-router'

import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { appHref, TOUR } from './content'

/** Browse the product by area; every card deep-links to the exact tab where the capability lives. */
export function ProductTour({ projectId }: { projectId: string }) {
  const [area, setArea] = useState<string>(TOUR[1].id)
  return (
    <Tabs value={area} onValueChange={setArea} className="gap-4" data-testid="about-tour">
      <TabsList variant="line" className="h-auto flex-wrap justify-start">
        {TOUR.map(({ id, label, icon: Icon, features }) => (
          <TabsTrigger key={id} value={id} className="flex-none px-3 py-1.5" data-testid={`about-tour-${id}`}>
            <Icon /> {label}
            <span className="rounded-full bg-muted px-1.5 text-[10px] font-semibold text-muted-foreground">{features.length}</span>
          </TabsTrigger>
        ))}
      </TabsList>
      {TOUR.map(({ id, blurb, open, features }) => (
        <TabsContent key={id} value={id} className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">{blurb}</p>
            <Button size="sm" asChild>
              <Link to={appHref(projectId, open)}>
                {open.label} <ArrowRight />
              </Link>
            </Button>
          </div>
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {features.map(({ title, description, icon: Icon, link }) => (
              <li key={title} className="flex">
                <Link
                  to={appHref(projectId, link)}
                  className="group flex w-full gap-3 rounded-xl border bg-card p-4 transition outline-none hover:border-primary/40 hover:shadow-md focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-2 text-sm font-semibold">
                      {title}
                      <ArrowUpRight className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
                    </span>
                    <span className="mt-1 block text-sm text-muted-foreground">{description}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </TabsContent>
      ))}
    </Tabs>
  )
}
