import {
  Button,
  Form,
  Input,
  Modal,
  Select,
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
import { useAuth } from '../auth/AuthContext'

type RoleBrief = { id: string; code: string; name: string }

type UserRow = {
  id: string
  email: string
  display_name: string | null
  role: string
  disabled: boolean
  created_at?: string | null
  roles?: RoleBrief[]
}

type AccountForm = {
  email: string
  password: string
  display_name?: string
  role_id?: string
}

export default function UsersPage({ mode }: { mode: 'clients' | 'admins' }) {
  const listRole = mode === 'clients' ? 'user' : 'admin'
  const title = mode === 'clients' ? 'C端用户' : '管理员'
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const [roleModal, setRoleModal] = useState<UserRow | null>(null)
  const [roleId, setRoleId] = useState<string>()
  const [form] = Form.useForm<AccountForm>()
  const qc = useQueryClient()
  const { me, isSuperAdmin, hasPermission } = useAuth()
  const meId = me?.id ?? null

  const { data: roleOptions = [] } = useQuery({
    queryKey: ['role-options'],
    enabled: hasPermission('admin:manage'),
    queryFn: async () => (await api.get<RoleBrief[]>('/api/admin/role-options')).data,
  })

  const staffRoleOptions = useMemo(
    () => roleOptions.filter((r) => r.code !== 'user' && r.code !== 'super_admin'),
    [roleOptions],
  )

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

  const assignRole = useMutation({
    mutationFn: async ({ id, role_id }: { id: string; role_id: string }) =>
      api.patch(`/api/admin/users/${id}/role`, { role_id }),
    onSuccess: () => {
      message.success('角色已更新')
      setRoleModal(null)
      qc.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        '赋角失败'
      message.error(typeof detail === 'string' ? detail : '赋角失败')
    },
  })

  const createAdmin = useMutation({
    mutationFn: async (values: AccountForm) => api.post('/api/admin/users/admins', values),
    onSuccess: () => {
      message.success('已创建管理员')
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

  const showCreate =
    (mode === 'clients' && hasPermission('user:create')) ||
    (mode === 'admins' && hasPermission('admin:manage'))

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
        render: (_role: string, row) => {
          const name = row.roles?.[0]?.name || row.role
          return row.role === 'super_admin' ? (
            <Tag color="gold">{name}</Tag>
          ) : (
            <Tag>{name}</Tag>
          )
        },
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
          const locked =
            isSuper ||
            isSelf ||
            (mode === 'admins' && !isSuperAdmin) ||
            !hasPermission('user:disable')
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
    if (mode === 'admins' && hasPermission('admin:manage')) {
      base.push({
        title: '操作',
        render: (_, row) =>
          row.role === 'super_admin' ? (
            '—'
          ) : (
            <Button
              size="small"
              onClick={() => {
                setRoleModal(row)
                setRoleId(row.roles?.[0]?.id)
              }}
            >
              分配角色
            </Button>
          ),
      })
    }
    return base
  }, [mode, meId, isSuperAdmin, patch, hasPermission])

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
            {mode === 'admins' ? '新建管理员' : '新建用户'}
          </Button>
        )}
      </Space>
      <Table rowKey="id" loading={isLoading} dataSource={data} columns={columns} />
      <Modal
        title={mode === 'admins' ? '新建管理员' : '新建用户'}
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
            <Input autoComplete="off" placeholder="请输入账号" />
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
          {mode === 'admins' ? (
            <Form.Item name="role_id" label="角色">
              <Select
                allowClear
                placeholder="默认普通管理员"
                options={staffRoleOptions.map((r) => ({ value: r.id, label: r.name }))}
              />
            </Form.Item>
          ) : null}
        </Form>
      </Modal>
      <Modal
        title="分配角色"
        open={Boolean(roleModal)}
        onCancel={() => setRoleModal(null)}
        onOk={() => {
          if (!roleModal || !roleId) return
          assignRole.mutate({ id: roleModal.id, role_id: roleId })
        }}
        confirmLoading={assignRole.isPending}
        destroyOnHidden
      >
        <Select
          style={{ width: '100%' }}
          value={roleId}
          onChange={setRoleId}
          options={staffRoleOptions.map((r) => ({ value: r.id, label: `${r.name}（${r.code}）` }))}
        />
      </Modal>
    </div>
  )
}
