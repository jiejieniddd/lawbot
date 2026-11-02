import {
  Button,
  Form,
  Input,
  Modal,
  Space,
  Switch,
  Table,
  Tag,
  message,
  type TableColumnsType,
} from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api } from '../api/client'

type UserRow = {
  id: string
  email: string
  display_name: string | null
  role: string
  disabled: boolean
  created_at?: string | null
}

type AccountForm = {
  email: string
  password: string
  display_name?: string
}

function roleLabel(role: string): string {
  if (role === 'super_admin') return '超级管理员'
  if (role === 'admin') return '普通管理员'
  return 'C端用户'
}

export default function UsersPage({ mode }: { mode: 'clients' | 'admins' }) {
  const listRole = mode === 'clients' ? 'user' : 'admin'
  const title = mode === 'clients' ? 'C端用户' : '管理员'
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm<AccountForm>()
  const qc = useQueryClient()

  const { data: me } = useQuery({
    queryKey: ['admin-me'],
    queryFn: async () => {
      const res = await api.get<UserRow>('/api/admin/auth/me')
      return res.data
    },
  })

  const isSuperAdmin = me?.role === 'super_admin'
  const meId = me?.id ?? null

  const { data, isLoading } = useQuery({
    queryKey: ['users', listRole, search],
    queryFn: async () => {
      const res = await api.get<UserRow[]>('/api/admin/users', {
        params: { role: listRole, ...(search ? { q: search } : {}) },
      })
      return res.data
    },
  })

  const patch = useMutation({
    mutationFn: async ({ id, disabled }: { id: string; disabled: boolean }) =>
      api.patch(`/api/admin/users/${id}`, { disabled }),
    onSuccess: () => {
      message.success('已更新')
      qc.invalidateQueries({ queryKey: ['users', listRole] })
      qc.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        '更新失败'
      message.error(typeof detail === 'string' ? detail : '更新失败')
    },
  })

  const createAdmin = useMutation({
    mutationFn: async (values: AccountForm) => api.post('/api/admin/users/admins', values),
    onSuccess: () => {
      message.success('已创建普通管理员')
      setOpen(false)
      form.resetFields()
      qc.invalidateQueries({ queryKey: ['users', 'admin'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        '创建失败'
      message.error(typeof detail === 'string' ? detail : '创建失败')
    },
  })

  const createClient = useMutation({
    mutationFn: async (values: AccountForm) => api.post('/api/admin/users/clients', values),
    onSuccess: () => {
      message.success('已创建用户')
      setOpen(false)
      form.resetFields()
      qc.invalidateQueries({ queryKey: ['users', 'user'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        '创建失败'
      message.error(typeof detail === 'string' ? detail : '创建失败')
    },
  })

  const showCreate = mode === 'clients' || (mode === 'admins' && isSuperAdmin)

  const columns: TableColumnsType<UserRow> = useMemo(() => {
    const base: TableColumnsType<UserRow> = [
      { title: '账号', dataIndex: 'email' },
      {
        title: '昵称',
        dataIndex: 'display_name',
        render: (v: string | null) => v || '—',
      },
    ]
    if (mode === 'admins') {
      base.push({
        title: '角色',
        dataIndex: 'role',
        render: (role: string) =>
          role === 'super_admin' ? (
            <Tag color="gold">{roleLabel(role)}</Tag>
          ) : (
            <Tag>{roleLabel(role)}</Tag>
          ),
      })
    }
    base.push(
      {
        title: '禁用',
        dataIndex: 'disabled',
        width: 100,
        render: (disabled: boolean, row) => {
          const isSuper = row.role === 'super_admin' || row.email === 'root'
          const isSelf = meId === row.id
          const locked = isSuper || isSelf || (mode === 'admins' && !isSuperAdmin)
          let titleHint: string | undefined
          if (isSuper) titleHint = '不能禁用超级管理员'
          else if (isSelf) titleHint = '不能禁用当前登录管理员'
          else if (mode === 'admins' && !isSuperAdmin) titleHint = '普通管理员只能管理 C 端用户'
          return (
            <Switch
              checked={disabled}
              disabled={locked}
              title={titleHint}
              onChange={(v) => patch.mutate({ id: row.id, disabled: v })}
            />
          )
        },
      },
      {
        title: '创建时间',
        dataIndex: 'created_at',
        render: (v: string | null | undefined) => (v ? new Date(v).toLocaleString() : '—'),
      },
    )
    return base
  }, [mode, meId, isSuperAdmin, patch])

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <h2 style={{ margin: 0 }}>{title}</h2>
        <Input.Search
          allowClear
          placeholder="搜索账号 / 昵称"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onSearch={(v) => setSearch(v.trim())}
          style={{ width: 260 }}
        />
        {showCreate && (
          <Button type="primary" onClick={() => setOpen(true)}>
            {mode === 'admins' ? '新建普通管理员' : '新建用户'}
          </Button>
        )}
      </Space>
      <Table rowKey="id" loading={isLoading} dataSource={data} columns={columns} />
      <Modal
        title={mode === 'admins' ? '新建普通管理员' : '新建用户'}
        open={open}
        onCancel={() => {
          setOpen(false)
          form.resetFields()
        }}
        onOk={() => form.submit()}
        confirmLoading={createAdmin.isPending || createClient.isPending}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(v) =>
            mode === 'admins' ? createAdmin.mutate(v) : createClient.mutate(v)
          }
        >
          <Form.Item name="email" label="账号" rules={[{ required: true, message: '请输入账号' }]}>
            <Input autoComplete="off" placeholder="账号（非邮箱亦可）" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, min: 6, message: '密码至少 6 位' }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="display_name" label="昵称">
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
