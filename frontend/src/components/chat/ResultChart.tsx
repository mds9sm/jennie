import { useState } from 'react'
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts'
import { BarChart3, TrendingUp, PieChart as PieIcon } from 'lucide-react'

interface Props {
  columns: string[]
  rows: unknown[][]
}

const COLORS = ['#0ea5e9', '#8b5cf6', '#f59e0b', '#10b981', '#ef4444', '#ec4899', '#6366f1', '#14b8a6']

type ChartType = 'bar' | 'line' | 'pie' | null

function detectChartType(columns: string[], rows: unknown[][]): ChartType {
  if (rows.length < 2 || columns.length < 2) return null

  // Need at least one string/label column and one numeric column
  const hasNumeric = rows[0]?.some(v => typeof v === 'number' || (typeof v === 'string' && !isNaN(Number(v)) && v.trim() !== ''))
  if (!hasNumeric) return null

  // If small number of rows with one label + one value → pie chart
  if (rows.length <= 8 && columns.length === 2) return 'pie'

  // If there's a date-like column → line chart
  const hasDate = columns.some(c =>
    /date|day|week|month|year|time|period/i.test(c)
  )
  if (hasDate) return 'line'

  // Default to bar chart
  return 'bar'
}

function prepareData(columns: string[], rows: unknown[][]): Record<string, unknown>[] {
  return rows.map(row => {
    const obj: Record<string, unknown> = {}
    columns.forEach((col, i) => {
      const val = row[i]
      // Try to convert to number if possible
      if (typeof val === 'string' && !isNaN(Number(val)) && val.trim() !== '') {
        obj[col] = Number(val)
      } else {
        obj[col] = val
      }
    })
    return obj
  })
}

function findLabelAndValueColumns(columns: string[], data: Record<string, unknown>[]): { label: string; values: string[] } {
  // Label column: first non-numeric column
  // Value columns: all numeric columns
  const label = columns.find(c => {
    const sample = data[0]?.[c]
    return typeof sample === 'string'
  }) || columns[0]

  const values = columns.filter(c => {
    const sample = data[0]?.[c]
    return typeof sample === 'number' && c !== label
  })

  return { label, values: values.length > 0 ? values : [columns[columns.length - 1]] }
}

export default function ResultChart({ columns, rows }: Props) {
  const suggestedType = detectChartType(columns, rows)
  const [chartType, setChartType] = useState<ChartType>(suggestedType)

  if (!suggestedType && !chartType) return null

  const data = prepareData(columns, rows)
  const { label, values } = findLabelAndValueColumns(columns, data)

  if (!chartType) return null

  return (
    <div className="mt-2 border border-gray-200 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-50 border-b border-gray-200">
        <span className="text-[10px] font-medium text-gray-500 uppercase">Chart</span>
        <div className="flex gap-1">
          <button onClick={() => setChartType('bar')}
            className={`p-1 rounded ${chartType === 'bar' ? 'bg-genie-100 text-genie-700' : 'text-gray-400 hover:text-gray-600'}`}
            title="Bar chart">
            <BarChart3 size={12} />
          </button>
          <button onClick={() => setChartType('line')}
            className={`p-1 rounded ${chartType === 'line' ? 'bg-genie-100 text-genie-700' : 'text-gray-400 hover:text-gray-600'}`}
            title="Line chart">
            <TrendingUp size={12} />
          </button>
          <button onClick={() => setChartType('pie')}
            className={`p-1 rounded ${chartType === 'pie' ? 'bg-genie-100 text-genie-700' : 'text-gray-400 hover:text-gray-600'}`}
            title="Pie chart">
            <PieIcon size={12} />
          </button>
          <button onClick={() => setChartType(null)}
            className="text-[10px] text-gray-400 hover:text-gray-600 px-1">
            Hide
          </button>
        </div>
      </div>
      <div className="p-3 bg-white" style={{ height: 260 }}>
        <ResponsiveContainer width="100%" height="100%">
          {chartType === 'bar' ? (
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey={label} tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip contentStyle={{ fontSize: 11 }} />
              {values.length > 1 && <Legend wrapperStyle={{ fontSize: 10 }} />}
              {values.map((v, i) => (
                <Bar key={v} dataKey={v} fill={COLORS[i % COLORS.length]} radius={[2, 2, 0, 0]} />
              ))}
            </BarChart>
          ) : chartType === 'line' ? (
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey={label} tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip contentStyle={{ fontSize: 11 }} />
              {values.length > 1 && <Legend wrapperStyle={{ fontSize: 10 }} />}
              {values.map((v, i) => (
                <Line key={v} type="monotone" dataKey={v} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={{ r: 3 }} />
              ))}
            </LineChart>
          ) : (
            <PieChart>
              <Pie
                data={data.map(d => ({ name: String(d[label]), value: Number(d[values[0]]) || 0 }))}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={90}
                label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
                labelLine={{ strokeWidth: 1 }}
                style={{ fontSize: 10 }}
              >
                {data.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ fontSize: 11 }} />
            </PieChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  )
}
