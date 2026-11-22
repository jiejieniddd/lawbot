<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { mountPixelToggle, type PixelToggleOptions } from './PixelToggleEngine.js'

/** Engine .pixel-switch is 520×272, border-radius 86px, then SWITCH_SCALE 0.83. */
const TRACK_W = 520 * 0.83
const TRACK_H = 272 * 0.83
const TRACK_RADIUS = 86 // matches .pixel-switch { border-radius: 86px }
const SCENE_W = 720
const SCENE_H = 540
/** Extra plate around the track so the knob isn’t clipped. */
const PLATE_PAD = 4

const props = withDefaults(
  defineProps<{
    checked?: boolean
    /** Visual height of the switch track in the toolbar. */
    height?: number
    sound?: boolean
    reducedMotion?: boolean
  }>(),
  {
    checked: false,
    /* Align with ChatView .avatar.sm (28px) + stage-user chip (~36px with pad). */
    height: 28,
    sound: true,
  },
)

const emit = defineEmits<{
  'update:checked': [value: boolean]
}>()

const hostRef = ref<HTMLElement | null>(null)
let controller: ReturnType<typeof mountPixelToggle> | null = null
let syncing = false

const scale = computed(() => props.height / TRACK_H)
const hostStyle = computed(() => {
  const s = scale.value
  const trackW = TRACK_W * s
  const trackH = props.height
  const hostW = trackW + PLATE_PAD * 2
  const hostH = trackH + PLATE_PAD * 2
  const sceneW = SCENE_W * s
  const sceneH = SCENE_H * s
  // Screen radius of the switch corner, then expand by pad (concentric rounded rect).
  const switchR = (TRACK_RADIUS * props.height) / 272
  const plateR = switchR + PLATE_PAD
  return {
    width: `${Math.round(hostW)}px`,
    height: `${Math.round(hostH)}px`,
    borderRadius: `${plateR.toFixed(1)}px`,
    '--pixel-display-scale': String(s),
    '--pixel-scene-shift-x': `${(hostW - sceneW) / 2}px`,
    '--pixel-scene-shift-y': `${(hostH - sceneH) / 2}px`,
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
  <div
    class="pixel-toggle-host"
    :class="checked ? 'is-day' : 'is-night'"
    :style="hostStyle"
    title="切换日间/夜间主题"
  >
    <div ref="hostRef" class="pixel-toggle-scale" data-motion-component="pixel-toggle" />
  </div>
</template>

<style scoped>
.pixel-toggle-host {
  position: relative;
  flex-shrink: 0;
  /* Don’t clip the frosted knob; plate is already inset larger than the track. */
  overflow: visible;
  line-height: 0;
  padding: 0;
  cursor: pointer;
  border: 1px solid rgba(0, 0, 0, 0.12);
}

.pixel-toggle-host.is-day {
  background: #eeede9;
}

.pixel-toggle-host.is-night {
  background: #1c1c1f;
  border-color: rgba(255, 255, 255, 0.14);
}

.pixel-toggle-scale {
  width: 720px;
  height: 540px;
  transform: translate(
      var(--pixel-scene-shift-x, 0),
      var(--pixel-scene-shift-y, 0)
    )
    scale(var(--pixel-display-scale, 0.195));
  transform-origin: top left;
}

.pixel-toggle-host :deep([data-motion-surface]) {
  width: 720px !important;
}

.pixel-toggle-host :deep(button:focus-visible) {
  outline: 2px solid #888;
  outline-offset: 2px;
}
</style>
