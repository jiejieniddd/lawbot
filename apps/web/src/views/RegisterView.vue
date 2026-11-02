<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { AUTH_FOOTER_DISCLAIMER } from '../constants/disclaimer'
import { useAuthStore } from '../stores/auth'

const email = ref('')
const password = ref('')
const displayName = ref('')
const loading = ref(false)
const auth = useAuthStore()
const router = useRouter()

async function onSubmit() {
  loading.value = true
  try {
    await auth.register(email.value, password.value, displayName.value || undefined)
    router.push('/chat')
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
      <h1>注册 LawBot</h1>
      <el-form @submit.prevent="onSubmit">
        <el-form-item label="昵称">
          <el-input v-model="displayName" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="email" type="email" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="password" type="password" autocomplete="new-password" show-password />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading" style="width: 100%">
          注册并进入
        </el-button>
      </el-form>
      <p class="hint">
        已有账号？
        <router-link to="/login">登录</router-link>
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
