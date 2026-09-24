interface Props {
  columns: string[]
  rows: unknown[][]
}

export default function ResultsTable({ columns, rows }: Props) {
  if (!columns.length) return null

  return (
    <div className="border border-gray-200 rounded-lg">
      <table className="divide-y divide-gray-200 text-sm w-max">
        <thead className="bg-gray-50 sticky top-0 z-10">
          <tr>
            <th className="px-2 py-2 text-left text-[10px] font-medium text-gray-400 w-8">#</th>
            {columns.map((col, i) => (
              <th key={i} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap min-w-[120px]">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-100">
          {rows.map((row, i) => (
            <tr key={i} className="hover:bg-gray-50">
              <td className="px-2 py-1.5 text-[10px] text-gray-300 font-mono">{i + 1}</td>
              {(row as unknown[]).map((cell, j) => (
                <td key={j} className="px-3 py-1.5 whitespace-nowrap text-gray-700 font-mono text-xs max-w-[300px] truncate" title={cell != null ? String(cell) : ''}>
                  {cell === null ? <span className="text-gray-300 italic">NULL</span> : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
