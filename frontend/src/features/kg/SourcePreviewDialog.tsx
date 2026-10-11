import { useQuery } from '@tanstack/react-query'

import { ErrorState, LoadingState } from '@/components/common/states'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { kgApi } from '@/lib/api/endpoints'
import type { SourceDocument } from '@/lib/api/types'
import { plural } from '@/lib/format'
import { queryKeys } from '@/lib/query'

/** Read-only preview of a project source: column profile and rows for CSV, text excerpt for documents. */
export function SourcePreviewDialog({ document, onClose }: { document: SourceDocument; onClose: () => void }) {
  const preview = useQuery({ queryKey: queryKeys.sourcePreview(document.id), queryFn: () => kgApi.preview(document.id) })
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl" data-testid="source-preview">
        <DialogHeader>
          <DialogTitle>{document.filename}</DialogTitle>
          <DialogDescription>
            {preview.data?.kind === 'table'
              ? `${plural(preview.data.total_rows, 'record')} · ${plural(preview.data.columns.length, 'column')} · structured source`
              : `${document.page_count ? `${plural(document.page_count, 'page')} · ` : ''}${plural(document.chunk_count, 'chunk')} · document`}
          </DialogDescription>
        </DialogHeader>
        {preview.isPending ? (
          <LoadingState />
        ) : preview.isError ? (
          <ErrorState error={preview.error} />
        ) : preview.data.kind === 'table' ? (
          <div className="space-y-4">
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground">
                <tr>
                  <th className="py-1 font-medium">Column</th>
                  <th className="py-1 font-medium">Inferred type</th>
                  <th className="py-1 text-right font-medium">Filled</th>
                  <th className="py-1 pl-4 font-medium">Sample values</th>
                </tr>
              </thead>
              <tbody>
                {preview.data.columns.map((column) => (
                  <tr key={column.name} className="border-t">
                    <td className="py-1 font-mono">{column.name}</td>
                    <td className="py-1">{column.inferred_datatype}</td>
                    <td className="py-1 text-right tabular-nums">
                      {column.non_empty}/{preview.data.total_rows}
                    </td>
                    <td className="py-1 pl-4 text-muted-foreground">{column.sample_values.join(', ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full text-xs">
                <thead className="bg-muted/60">
                  <tr>
                    {preview.data.columns.map((c) => (
                      <th key={c.name} className="px-2 py-1.5 text-left font-mono font-medium">
                        {c.name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.data.rows.map((row) => (
                    <tr key={row.row_number} className="border-t">
                      {preview.data.columns.map((c) => (
                        <td key={c.name} className="px-2 py-1 whitespace-nowrap">
                          {row.values[c.name]}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <p className="max-h-[60vh] overflow-y-auto rounded-lg bg-muted/40 p-3 text-xs leading-relaxed whitespace-pre-wrap">
            {preview.data.text_excerpt}
            {document.char_count > preview.data.text_excerpt.length && '…'}
          </p>
        )}
      </DialogContent>
    </Dialog>
  )
}
