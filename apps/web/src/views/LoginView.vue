<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { AUTH_FOOTER_DISCLAIMER } from '../constants/disclaimer'
import { useAuthStore } from '../stores/auth'

const email = ref('')
const password = ref('')
const loading = ref(false)
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

async function onSubmit() {
  loading.value = true
  try {
    await auth.login(email.value, password.value)
    router.push((route.query.redirect as string) || '/chat')
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page">
    <el-card class="card">
      <h1>LawBot 登录</h1>
      <el-form @submit.prevent="onSubmit">
        <el-form-item label="邮箱">
          <el-input v-model="email" type="email" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="password" type="password" autocomplete="current-password" show-password />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading" style="width: 100%">
          登录
        </el-button>
      </el-form>
      <p class="hint">
        没有账号？
        <router-link to="/register">注册</router-link>
      </p>
      <p class="foot-note">{{ AUTH_FOOTER_DISCLAIMER }}</p>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  background: linear-gradient(160deg, #e8eef5 0%, #f7f4ef 50%, #eef2f7 100%);
}
.card {
  width: min(420px, 92vw);
}
h1 {
  font-family: "Source Han Serif SC", "Noto Serif SC", Georgia, serif;
  margin: 0 0 1rem;
  font-size: 1.6rem;
}
.hint {
  margin-top: 1rem;
  color: #666;
}
.foot-note {
  margin-top: 1rem;
  font-size: 0.72rem;
  color: #999;
  line-height: 1.45;
}
</style>
