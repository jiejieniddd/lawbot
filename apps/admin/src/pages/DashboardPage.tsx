import { Alert, Card, Col, Empty, Row, Segmented, Space, Statistic } from 'antd'
import { Column, Line, Pie } from '@ant-design/charts'
import { useQuery } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { useMemo, useState, type ReactNode } from 'react'
import { api } from '../api/client'

type Stats = {
  users: number
  end_users: number
  admins: number
  conversations: number
  messages: number
  knowledge_documents: number
}

type SeriesPoint = {
  date: string
  new_end_users: number
  new_conversations: number
  new_messages: number
}

type StatsSeries = {
  days: number
  bucket: string
  timezone: string
  points: SeriesPoint[]
}

type DaysOption = 7 | 14 | 30

const chartCardBody = { overflow: 'hidden' as const }

function seriesAllZero(points: SeriesPoint[] | undefined) {
  if (!points?.length) return true
  return points.every(
    (p) => p.new_end_users === 0 && p.new_conversations === 0 && p.new_messages === 0,
  )
}

function detailText(data: unknown): string {
  if (data == null) return ''
  if (typeof data === 'string') return data.trim()
  if (typeof data === 'object' && data !== null && 'detail' in data) {
    const d = (data as { detail: unknown }).detail
    if (typeof d === 'string') return d.trim()
    if (Array.isArray(d)) {
      return d
        .map((item) =>
          typeof item === 'object' && item && 'msg' in item
            ? String((item as { msg: unknown }).msg)
            : String(item),
        )
        .filter(Boolean)
        .join('；')
    }
  }
  return ''
}

/** Map axios/network errors to short Chinese copy. Only 403 mentions permissions. */
function formatStatsError(err: unknown, scope: 'overview' | 'series'): string {
  const label = scope === 'overview' ? '概览' : '趋势'
  if (!isAxiosError(err)) {
    return `${label}统计加载失败`
  }
  if (!err.response) {
    return `${label}统计服务不可用，请检查网络或后端是否在运行`
  }
  const status = err.response.status
  const detail = detailText(err.response.data)
  if (status === 403) {
    return `${label}无权限（需要 stats:read）`
  }
  if (status === 404) {
    return scope === 'series'
      ? '趋势接口未加载，请重启 API 后再试'
      : '概览接口不存在，请确认后端版本并重启 API'
  }
  if (status >= 500) {
    return detail ? `${label}统计异常：${detail}` : `${label}统计服务异常（${status}）`
  }
  if (status === 422) {
    return detail || `${label}参数无效`
  }
  return detail || `${label}加载失败（${status}）`
}

function SeriesChartBody({
  loading,
  isError,
  error,
  isSuccess,
  empty,
  children,
}: {
  loading: boolean
  isError: boolean
  error: unknown
  isSuccess: boolean
  empty: boolean
  children: ReactNode
}) {
  if (loading) return null
  if (isError) {
    return <Alert type="error" showIcon message={formatStatsError(error, 'series')} />
  }
  if (isSuccess && empty) {
    return <Empty description="暂无数据" />
  }
  return <>{children}</>
}

export default function DashboardPage() {
  const [days, setDays] = useState<DaysOption>(14)

  const overview = useQuery({
    queryKey: ['stats'],
    queryFn: async () => (await api.get<Stats>('/api/admin/stats/overview')).data,
  })

  const series = useQuery({
    queryKey: ['stats-series', days],
    queryFn: async () =>
      (await api.get<StatsSeries>('/api/admin/stats/series', { params: { days } })).data,
  })

  const activityLineData = useMemo(() => {
    const points = series.data?.points ?? []
    return points.flatMap((p) => [
      { date: p.date, value: p.new_conversations, series: '新增会话' },
      { date: p.date, value: p.new_messages, series: '新增消息' },
    ])
  }, [series.data?.points])

  const userColumnData = useMemo(
    () =>
      (series.data?.points ?? []).map((p) => ({
        date: p.date,
        value: p.new_end_users,
      })),
    [series.data?.points],
  )

  const rolePieData = useMemo(() => {
    const endUsers = overview.data?.end_users ?? 0
    const admins = overview.data?.admins ?? 0
    return [
      { type: 'C端用户', value: endUsers },
      { type: '管理员', value: admins },
    ]
  }, [overview.data?.admins, overview.data?.end_users])

  const emptySeries = seriesAllZero(series.data?.points)
  const emptyRoles =
    (overview.data?.end_users ?? 0) === 0 && (overview.data?.admins ?? 0) === 0

  return (
    <div className="dashboard-page">
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }} wrap>
        <h2 style={{ margin: 0 }}>仪表盘</h2>
        <Segmented
          value={days}
          onChange={(v) => setDays(v as DaysOption)}
          options={[
            { label: '近 7 日', value: 7 },
            { label: '近 14 日', value: 14 },
            { label: '近 30 日', value: 30 },
          ]}
        />
      </Space>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={overview.isLoading}>
            <Statistic title="C端用户" value={overview.data?.end_users ?? 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={overview.isLoading}>
            <Statistic title="管理员" value={overview.data?.admins ?? 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={overview.isLoading}>
            <Statistic title="会话" value={overview.data?.conversations ?? 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={overview.isLoading}>
            <Statistic title="消息" value={overview.data?.messages ?? 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={overview.isLoading}>
            <Statistic title="知识文档" value={overview.data?.knowledge_documents ?? 0} />
          </Card>
        </Col>
      </Row>

      {overview.isError && (
        <Alert
          style={{ marginTop: 16 }}
          type="error"
          showIcon
          message={formatStatsError(overview.error, 'overview')}
        />
      )}

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={14}>
          <Card title="新增会话与消息" loading={series.isLoading} styles={{ body: chartCardBody }}>
            <SeriesChartBody
              loading={series.isLoading}
              isError={series.isError}
              error={series.error}
              isSuccess={series.isSuccess}
              empty={emptySeries}
            >
              <div className="dashboard-chart">
                <Line
                  data={activityLineData}
                  xField="date"
                  yField="value"
                  colorField="series"
                  height={280}
                  autoFit
                  legend={{ position: 'top' }}
                  axis={{
                    x: { title: false },
                    y: { title: false, min: 0 },
                  }}
                  style={{ lineWidth: 2 }}
                />
              </div>
            </SeriesChartBody>
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="用户角色分布" loading={overview.isLoading} styles={{ body: chartCardBody }}>
            {overview.isError ? (
              <Alert type="error" showIcon message={formatStatsError(overview.error, 'overview')} />
            ) : emptyRoles && !overview.isLoading ? (
              <Empty description="暂无数据" />
            ) : (
              <div className="dashboard-chart">
                <Pie
                  data={rolePieData}
                  angleField="value"
                  colorField="type"
                  height={280}
                  autoFit
                  innerRadius={0.55}
                  legend={{ position: 'bottom' }}
                  label={{ text: 'type' }}
                />
              </div>
            )}
          </Card>
        </Col>
        <Col xs={24}>
          <Card title="新增 C 端用户" loading={series.isLoading} styles={{ body: chartCardBody }}>
            <SeriesChartBody
              loading={series.isLoading}
              isError={series.isError}
              error={series.error}
              isSuccess={series.isSuccess}
              empty={emptySeries}
            >
              <div className="dashboard-chart">
                <Column
                  data={userColumnData}
                  xField="date"
                  yField="value"
                  height={260}
                  autoFit
                  axis={{
                    x: { title: false },
                    y: { title: false, min: 0 },
                  }}
                />
              </div>
            </SeriesChartBody>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
