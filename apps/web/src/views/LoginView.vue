<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { AUTH_FOOTER_DISCLAIMER } from '../constants/disclaimer'
import { useAuthStore } from '../stores/auth'
import '../styles/auth.css'

type LoginMode = 'password' | 'email_code'

const mode = ref<LoginMode>('password')
const account = ref('')
const password = ref('')
const code = ref('')
const loading = ref(false)
const sending = ref(false)
const cooldown = ref(0)
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

let timer: number | null = null

const lead = computed(() =>
  mode.value === 'password' ? '用邮箱和密码登录' : '用邮箱验证码登录',
)

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

watch(mode, (next) => {
  if (next === 'password') {
    code.value = ''
  } else {
    password.value = ''
  }
})

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
    const data = await auth.sendLoginCode(account.value.trim())
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
  if (mode.value === 'password') {
    if (!password.value || password.value.length < 6) {
      ElMessage.error('请输入密码')
      return
    }
  } else if (!/^\d{6}$/.test(code.value.trim())) {
    ElMessage.error('请输入 6 位验证码')
    return
  }
  loading.value = true
  try {
    if (mode.value === 'password') {
      await auth.loginPassword(account.value.trim(), password.value)
    } else {
      await auth.loginWithCode(account.value.trim(), code.value.trim())
    }
    router.push((route.query.redirect as string) || '/chat')
  } catch (e) {
    ElMessage.error((e as Error).message || '登录失败')
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
      <p class="brand-note">面试答疑与就业方向辅导。回答仅供参考，不构成录用承诺。</p>
    </aside>
    <section class="form-pane">
      <div class="form-block">
        <div class="sticker-row" aria-hidden="true">
          <span class="sticker coral" />
          <span class="sticker mint" />
          <span class="sticker sunny" />
        </div>
        <h1>登录</h1>
        <p class="lead">{{ lead }}</p>
        <el-segmented
          v-model="mode"
          class="mode-switch"
          :options="[
            { label: '密码登录', value: 'password' },
            { label: '验证码登录', value: 'email_code' },
          ]"
        />
        <el-form class="auth-form" label-position="top" @submit.prevent="onSubmit">
          <el-form-item label="邮箱">
            <el-input
              v-model="account"
              type="email"
              autocomplete="username"
              size="large"
              placeholder="请输入邮箱"
            />
          </el-form-item>
          <el-form-item v-if="mode === 'password'" label="密码">
            <el-input
              v-model="password"
              type="password"
              autocomplete="current-password"
              show-password
              size="large"
            />
          </el-form-item>
          <el-form-item v-else label="验证码">
            <div class="code-row">
              <el-input
                v-model="code"
                inputmode="numeric"
                maxlength="6"
                autocomplete="one-time-code"
                size="large"
                placeholder="6 位数字"
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
          <el-button
            type="primary"
            native-type="submit"
            :loading="loading"
            size="large"
            class="submit"
          >
            登录
          </el-button>
        </el-form>
        <p class="hint">
          <router-link to="/forgot-password">忘记密码</router-link>
        </p>
        <p class="hint">
          没有账号？
          <router-link to="/register">注册</router-link>
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
