<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import { AUTH_FOOTER_DISCLAIMER } from '../constants/disclaimer'

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
    <aside class="brand-pane" aria-label="LawBot">
      <div class="brand-mark">LawBot</div>
      <p class="brand-line">找回密码</p>
      <p class="brand-note">验证码会发到已注册邮箱。未注册或已停用的地址不会收到邮件。</p>
    </aside>
    <section class="form-pane">
      <div class="form-block">
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
              重置密码
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
.auth-shell {
  min-height: 100vh;
  min-height: 100dvh;
  display: grid;
  grid-template-columns: minmax(280px, 0.42fr) minmax(320px, 0.58fr);
  background: var(--bg);
}

.brand-pane {
  background: linear-gradient(
    165deg,
    color-mix(in srgb, var(--color-primary) 88%, #1a2332) 0%,
    var(--color-primary) 55%,
    color-mix(in srgb, var(--color-info) 55%, var(--color-primary)) 100%
  );
  color: #fff;
  padding: clamp(2rem, 6vw, 3.5rem);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.75rem;
  animation: brand-in 0.55s ease-out both;
}

.brand-mark {
  font-family: var(--font-ui);
  font-size: var(--fs-brand);
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.1;
}

.brand-line {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 500;
  opacity: 0.95;
}

.brand-note {
  margin: 0.5rem 0 0;
  max-width: 28ch;
  font-size: var(--fs-small);
  line-height: 1.55;
  opacity: 0.82;
}

.form-pane {
  display: grid;
  place-items: center;
  padding: 2rem 1.25rem;
  background: var(--surface);
}

.form-block {
  width: min(400px, 100%);
}

h1 {
  margin: 0;
  font-family: var(--font-ui);
  font-size: var(--fs-title);
  font-weight: 600;
  letter-spacing: -0.02em;
}

.lead {
  margin: 0.35rem 0 1.35rem;
  color: var(--muted);
  font-size: var(--fs-small);
}

.code-row {
  display: flex;
  gap: 0.5rem;
  width: 100%;
}

.code-row .el-input {
  flex: 1;
}

.submit {
  width: 100%;
  margin-top: 0.25rem;
}

.hint {
  margin-top: 1.1rem;
  color: var(--muted);
  font-size: var(--fs-small);
}

.foot-note {
  margin-top: 1.25rem;
  font-size: var(--fs-fine);
  color: var(--muted);
  line-height: 1.45;
}

@keyframes brand-in {
  from {
    opacity: 0;
    transform: translateX(-12px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .brand-pane {
    animation: none;
  }
}

@media (max-width: 840px) {
  .auth-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
  }
  .brand-pane {
    padding: 1.5rem 1.25rem;
    min-height: auto;
  }
  .brand-note {
    display: none;
  }
}
</style>
