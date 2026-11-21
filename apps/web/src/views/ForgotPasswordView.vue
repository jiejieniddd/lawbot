<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import { AUTH_FOOTER_DISCLAIMER } from '../constants/disclaimer'
import '../styles/auth.css'

const email = ref('')
const code = ref('')
const password = ref('')
const confirmPassword = ref('')
const sending = ref(false)
const resetting = ref(false)
const sent = ref(false)
const cooldown = ref(0)
const router = useRouter()

let timer: number | null = null

function isEmail(value: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())
}

function startCooldown(seconds: number) {
  cooldown.value = Math.max(1, seconds)
  if (timer != null) window.clearInterval(timer)
  timer = window.setInterval(() => {
    cooldown.value -= 1
    if (cooldown.value <= 0 && timer != null) {
      window.clearInterval(timer)
      timer = null
    }
  }, 1000)
}

onUnmounted(() => {
  if (timer != null) window.clearInterval(timer)
})

async function sendCode() {
  if (!isEmail(email.value)) {
    ElMessage.error('请输入有效邮箱')
    return
  }
  sending.value = true
  try {
    const data = await api<{ detail: string; retry_after_seconds: number }>(
      '/api/v1/auth/forgot-password/send',
      {
        method: 'POST',
        body: JSON.stringify({ email: email.value.trim() }),
      },
    )
    sent.value = true
    ElMessage.success(data.detail)
    startCooldown(data.retry_after_seconds || 60)
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    sending.value = false
  }
}

async function onReset() {
  if (!sent.value) return
  if (!isEmail(email.value)) {
    ElMessage.error('请输入有效邮箱')
    return
  }
  if (!/^\d{6}$/.test(code.value.trim())) {
    ElMessage.error('请输入 6 位验证码')
    return
  }
  if (password.value.length < 6 || password.value.length > 128) {
    ElMessage.error('密码长度须为 6–128 位')
    return
  }
  if (password.value !== confirmPassword.value) {
    ElMessage.error('两次输入的密码不一致')
    return
  }
  resetting.value = true
  try {
    const data = await api<{ detail: string }>('/api/v1/auth/forgot-password/reset', {
      method: 'POST',
      body: JSON.stringify({
        email: email.value.trim(),
        code: code.value.trim(),
        new_password: password.value,
      }),
    })
    ElMessage.success(data.detail || '密码已重置，请重新登录')
    await router.push('/login')
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    resetting.value = false
  }
}
</script>

<template>
  <div class="auth-shell">
    <aside class="brand-pane" aria-label="CareerBot">
      <div class="brand-mark">CareerBot</div>
      <p class="brand-line">找回密码</p>
      <p class="brand-note">验证码会发到已注册邮箱。未注册或已停用的地址不会收到邮件。</p>
    </aside>
    <section class="form-pane">
      <div class="form-block">
        <div class="sticker-row" aria-hidden="true">
          <span class="sticker sunny" />
          <span class="sticker coral" />
          <span class="sticker mint" />
        </div>
        <h1>忘记密码</h1>
        <p class="lead">使用邮箱验证码设置新密码</p>
        <el-form class="auth-form" label-position="top" @submit.prevent="onReset">
          <el-form-item label="邮箱">
            <div class="code-row">
              <el-input
                v-model="email"
                type="email"
                autocomplete="email"
                size="large"
                placeholder="请输入邮箱"
              />
              <el-button
                native-type="button"
                size="large"
                :loading="sending"
                :disabled="cooldown > 0"
                @click="sendCode"
              >
                {{ cooldown > 0 ? `${cooldown}s` : '发送验证码' }}
              </el-button>
            </div>
          </el-form-item>
          <template v-if="sent">
            <el-form-item label="验证码">
              <el-input
                v-model="code"
                inputmode="numeric"
                maxlength="6"
                autocomplete="one-time-code"
                size="large"
                placeholder="6 位数字"
              />
            </el-form-item>
            <el-form-item label="新密码">
              <el-input
                v-model="password"
                type="password"
                autocomplete="new-password"
                show-password
                size="large"
              />
            </el-form-item>
            <el-form-item label="确认密码">
              <el-input
                v-model="confirmPassword"
                type="password"
                autocomplete="new-password"
                show-password
                size="large"
              />
            </el-form-item>
            <el-button
              type="primary"
              native-type="submit"
              :loading="resetting"
              size="large"
              class="submit"
            >
              找回密码
            </el-button>
          </template>
        </el-form>
        <p class="hint">
          <router-link to="/login">返回登录</router-link>
        </p>
        <p class="foot-note">{{ AUTH_FOOTER_DISCLAIMER }}</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.sticker-row {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  transform: rotate(-2deg);
  width: fit-content;
}

.sticker {
  width: 16px;
  height: 16px;
  border: 2px solid var(--color-ink);
}

.sticker.coral {
  background: var(--color-coral);
}

.sticker.mint {
  background: var(--color-mint);
}

.sticker.sunny {
  background: var(--color-sunny);
}
</style>
