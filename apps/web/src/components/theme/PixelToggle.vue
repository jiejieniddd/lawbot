<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { mountPixelToggle, type PixelToggleOptions } from './PixelToggleEngine.js'

/** Logical switch size after .83 scene scale (520×272 × 0.83). */
const SWITCH_H = 272 * 0.83
const SCENE_W = 720
const SCENE_H = 540

const props = withDefaults(
  defineProps<{
    checked?: boolean
    /** Visual height of the switch in the toolbar. */
    height?: number
    sound?: boolean
    reducedMotion?: boolean
  }>(),
  {
    checked: false,
    height: 44,
    sound: true,
  },
)

const emit = defineEmits<{
  'update:checked': [value: boolean]
}>()

const hostRef = ref<HTMLElement | null>(null)
let controller: ReturnType<typeof mountPixelToggle> | null = null
let syncing = false

/** Scale so the frosted knob track is ~height px tall (crop scene chrome). */
const scale = computed(() => props.height / SWITCH_H)
const hostStyle = computed(() => {
  const s = scale.value
  const sceneW = SCENE_W * s
  const sceneH = SCENE_H * s
  return {
    width: `${Math.round(sceneW)}px`,
    height: `${props.height}px`,
    '--pixel-display-scale': String(s),
    '--pixel-scene-shift-y': `${(props.height - sceneH) / 2}px`,
  }
})

function engineOptions(): PixelToggleOptions {
  return {
    checked: props.checked,
    sound: props.sound,
    reducedMotion: props.reducedMotion,
    height: 540,
    onCheckedChange(next) {
      syncing = true
      emit('update:checked', next)
      queueMicrotask(() => {
        syncing = false
      })
    },
  }
}

onMounted(() => {
  if (!hostRef.value) return
  controller = mountPixelToggle(hostRef.value, engineOptions())
})

watch(
  () => props.checked,
  (next) => {
    if (syncing || !controller) return
    controller.update({ checked: !!next })
  },
)

watch(
  () => [props.sound, props.reducedMotion] as const,
  ([sound, reducedMotion]) => {
    controller?.update({ sound, reducedMotion, height: 540 })
  },
)

onBeforeUnmount(() => {
  controller?.destroy()
  controller = null
})
</script>

<template>
  <div class="pixel-toggle-host" :style="hostStyle" title="切换日间/夜间主题">
    <div ref="hostRef" class="pixel-toggle-scale" data-motion-component="pixel-toggle" />
  </div>
</template>

<style scoped>
.pixel-toggle-host {
  position: relative;
  flex-shrink: 0;
  overflow: hidden;
  line-height: 0;
  max-width: min(140px, 36vw);
  background: transparent;
}

.pixel-toggle-scale {
  width: 720px;
  height: 540px;
  transform: translateY(var(--pixel-scene-shift-y, 0)) scale(var(--pixel-display-scale, 0.195));
  transform-origin: top left;
}

.pixel-toggle-host :deep([data-motion-surface]) {
  width: 720px !important;
}

.pixel-toggle-host :deep(button:focus-visible) {
  outline: 2px solid var(--color-mint);
  outline-offset: 4px;
}
</style>
