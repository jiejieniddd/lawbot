<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { AUTH_FOOTER_DISCLAIMER } from '../constants/disclaimer'
import { useAuthStore } from '../stores/auth'
import '../styles/auth.css'

const account = ref('')
const password = ref('')
const code = ref('')
const displayName = ref('')
const loading = ref(false)
const sending = ref(false)
const cooldown = ref(0)
const auth = useAuthStore()
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
  if (!isEmail(account.value)) {
    ElMessage.error('请输入有效邮箱')
    return
  }
  sending.value = true
  try {
    const data = await auth.sendRegisterCode(account.value.trim())
    ElMessage.success(data.detail)
    startCooldown(data.retry_after_seconds || 60)
  } catch (e) {
    ElMessage.error((e as Error).message || '请求失败')
  } finally {
    sending.value = false
  }
}

async function onSubmit() {
  if (!isEmail(account.value)) {
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
  loading.value = true
  try {
    await auth.register(
      account.value.trim(),
      password.value,
      code.value.trim(),
      displayName.value || undefined,
    )
    router.push('/chat')
  } catch (e) {
    ElMessage.error((e as Error).message || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-shell">
    <aside class="brand-pane" aria-label="CareerBot">
      <div class="brand-mark">CareerBot</div>
      <p class="brand-line">计算机求职助手</p>
      <p class="brand-note">创建账号后即可开始会话。我们重视可追溯引用与清晰免责说明。</p>
    </aside>
    <section class="form-pane">
      <div class="form-block">
        <div class="sticker-row" aria-hidden="true">
          <span class="sticker mint" />
          <span class="sticker sunny" />
          <span class="sticker coral" />
        </div>
        <h1>注册</h1>
        <p class="lead">邮箱验证后创建账号并进入工作台</p>
        <el-form class="auth-form" label-position="top" @submit.prevent="onSubmit">
          <el-form-item label="昵称">
            <el-input v-model="displayName" size="large" placeholder="可选" />
          </el-form-item>
          <el-form-item label="邮箱">
            <div class="code-row">
              <el-input
                v-model="account"
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
                {{ cooldown > 0 ? `${cooldown}s` : '获取验证码' }}
              </el-button>
            </div>
          </el-form-item>
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
          <el-form-item label="密码">
            <el-input
              v-model="password"
              type="password"
              autocomplete="new-password"
              show-password
              size="large"
            />
          </el-form-item>
          <el-button
            type="primary"
            native-type="submit"
            :loading="loading"
            size="large"
            class="submit"
          >
            注册并进入
          </el-button>
        </el-form>
        <p class="hint">
          已有账号？
          <router-link to="/login">登录</router-link>
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
