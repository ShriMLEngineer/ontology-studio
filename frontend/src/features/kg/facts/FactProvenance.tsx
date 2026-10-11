import { FileSpreadsheet, FileText } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { FactDetail, FactSourceRef, SourceExcerpt } from '@/lib/api/types'
import { factStatement } from '../meta'
import { CheckList, EvidenceBadge, FactStatusBadge, Highlighted } from '../shared'

function RecordExcerpt({ source, excerpt }: { source: FactSourceRef; excerpt: SourceExcerpt | undefined }) {
  const record = excerpt?.record ?? source.record ?? {}
  return (
    <table className="w-full text-xs" data-testid="source-record">
      <tbody>
        {Object.entries(record).map(([column, value]) => (
          <tr key={column} className="border-t first:border-t-0">
            <th className="w-2/5 py-1 pr-2 text-left font-mono font-normal text-muted-foreground">{column}</th>
            <td className="py-1">{value || <span className="text-muted-foreground">(empty)</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function TextExcerpt({ source, excerpt }: { source: FactSourceRef; excerpt: SourceExcerpt | undefined }) {
  const text = excerpt?.text ?? source.context ?? ''
  if (!source.located) {
    return (
      <div className="space-y-1 text-xs">
        <p className="font-medium text-amber-800">Model quote - not found in the source text:</p>
        <blockquote className="border-l-2 border-amber-300 pl-2 text-muted-foreground italic">
          {source.llm_quote ? `“${source.llm_quote}”` : '(no quote provided)'}
        </blockquote>
      </div>
    )
  }
  return (
    <p className="max-h-56 overflow-y-auto rounded bg-muted/40 p-2 text-xs leading-relaxed whitespace-pre-wrap" data-testid="source-text">
      <Highlighted text={text} quote={source.quote} />
    </p>
  )
}

export function SourceList({ fact }: { fact: FactDetail }) {
  return (
    <ul className="space-y-3">
      {fact.sources.map((source, index) => {
        const excerpt = fact.excerpts[index]
        const location =
          source.kind === 'record'
            ? `Row ${source.row_number}${source.mapping_name ? ` · mapping '${source.mapping_name}'` : ''}`
            : `${source.page ? `Page ${source.page} · ` : ''}chunk ${(source.chunk_index ?? 0) + 1}`
        return (
          <li key={index} className="space-y-2 rounded-lg border p-2.5" data-testid="fact-source">
            <p className="flex items-center gap-1.5 text-xs font-medium">
              {source.kind === 'record' ? (
                <FileSpreadsheet className="size-3.5 text-emerald-600" />
              ) : (
                <FileText className="size-3.5 text-sky-600" />
              )}
              <span className="truncate">{source.document_name}</span>
              <span className="font-normal text-muted-foreground">· {location}</span>
              {excerpt && !excerpt.available && (
                <Badge variant="outline" className="ml-auto text-[10px]">
                  source deleted
                </Badge>
              )}
            </p>
            {source.kind === 'record' ? <RecordExcerpt source={source} excerpt={excerpt} /> : <TextExcerpt source={source} excerpt={excerpt} />}
          </li>
        )
      })}
    </ul>
  )
}

export function FactProvenance({ fact, showStatement = true }: { fact: FactDetail; showStatement?: boolean }) {
  return (
    <div className="space-y-4" data-testid="fact-provenance" data-fact-status={fact.status}>
      <div className="flex flex-wrap items-center gap-1.5">
        <FactStatusBadge status={fact.status} />
        <EvidenceBadge status={fact.evidence_status} />
        <Badge variant="outline" className="text-[10px]">
          {fact.kind}
        </Badge>
        <Badge variant="outline" className="text-[10px]">
          {fact.origin === 'llm' ? 'LLM extraction' : 'Structured mapping'}
        </Badge>
      </div>
      {showStatement && <p className="text-sm font-medium">{factStatement(fact)}</p>}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted-foreground">Ontology {fact.kind === 'type' ? 'class' : 'property'}</dt>
        <dd>
          {fact.kind === 'type' ? fact.object_label : fact.predicate_label}{' '}
          <span className="font-mono text-muted-foreground">{fact.predicate_id ?? `${fact.predicate_ref} (not defined)`}</span>
        </dd>
        {fact.subject_class_label && (
          <>
            <dt className="text-muted-foreground">Subject class</dt>
            <dd>{fact.subject_class_label}</dd>
          </>
        )}
        {fact.object_class_label && fact.kind === 'relationship' && (
          <>
            <dt className="text-muted-foreground">Object class</dt>
            <dd>{fact.object_class_label}</dd>
          </>
        )}
        {fact.datatype && (
          <>
            <dt className="text-muted-foreground">Datatype</dt>
            <dd>{fact.datatype}</dd>
          </>
        )}
        <dt className="text-muted-foreground">Build</dt>
        <dd>
          #{fact.build_number} · ontology v{fact.ontology_version}
        </dd>
      </dl>
      <section className="space-y-1.5">
        <h4 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Structural validation</h4>
        <CheckList checks={fact.structural.checks} />
      </section>
      <section className="space-y-1.5">
        <h4 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Evidence validation</h4>
        <CheckList checks={fact.evidence.checks} />
      </section>
      {fact.resolution.checks.length > 0 && (
        <section className="space-y-1.5">
          <h4 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Entity resolution</h4>
          <CheckList checks={fact.resolution.checks} />
        </section>
      )}
      <section className="space-y-1.5">
        <h4 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Source evidence</h4>
        <SourceList fact={fact} />
      </section>
    </div>
  )
}
