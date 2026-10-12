import { useState } from 'react'
import { ArrowRight, CheckCircle2 } from 'lucide-react'
import { Link } from 'react-router'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { appHref, PRINCIPLES, ROLES } from './content'

function PrincipleCards({ projectId }: { projectId: string }) {
  return (
    <ul className="grid gap-4 md:grid-cols-3">
      {PRINCIPLES.map(({ icon: Icon, title, summary, points, link }) => (
        <li key={title} className="flex">
          <Card className="w-full transition-shadow hover:shadow-md">
            <CardHeader>
              <div className="mb-2 flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Icon className="size-5" />
              </div>
              <CardTitle className="text-base">{title}</CardTitle>
              <CardDescription>{summary}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-1 flex-col gap-3">
              <ul className="space-y-1.5 text-sm">
                {points.map((point) => (
                  <li key={point} className="flex items-start gap-2">
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" />
                    {point}
                  </li>
                ))}
              </ul>
              <Button variant="link" size="sm" className="mt-auto w-fit px-0" asChild>
                <Link to={appHref(projectId, link)}>
                  {link.label} <ArrowRight />
                </Link>
              </Button>
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  )
}

function RolePicker({ projectId }: { projectId: string }) {
  const [role, setRole] = useState<string>(ROLES[0].id)
  return (
    <Card data-testid="about-roles">
      <CardHeader>
        <CardTitle>Where should I start?</CardTitle>
        <CardDescription>Pick the role closest to yours for a short path through the studio.</CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs value={role} onValueChange={setRole} className="gap-4">
          <TabsList variant="line" className="h-auto flex-wrap justify-start">
            {ROLES.map(({ id, label, icon: Icon }) => (
              <TabsTrigger key={id} value={id} className="flex-none px-3 py-1.5" data-testid={`about-role-${id}`}>
                <Icon /> {label}
              </TabsTrigger>
            ))}
          </TabsList>
          {ROLES.map(({ id, summary, steps, cta }) => (
            <TabsContent key={id} value={id} className="space-y-4">
              <p className="text-sm font-medium">{summary}</p>
              <ol className="space-y-2">
                {steps.map((step, index) => (
                  <li key={step} className="flex items-start gap-3 text-sm">
                    <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                      {index + 1}
                    </span>
                    <span className="pt-0.5">{step}</span>
                  </li>
                ))}
              </ol>
              <Button asChild size="sm">
                <Link to={appHref(projectId, cta)}>
                  {cta.label} <ArrowRight />
                </Link>
              </Button>
            </TabsContent>
          ))}
        </Tabs>
      </CardContent>
    </Card>
  )
}

export function Overview({ projectId }: { projectId: string }) {
  return (
    <div className="space-y-6">
      <PrincipleCards projectId={projectId} />
      <RolePicker projectId={projectId} />
    </div>
  )
}
