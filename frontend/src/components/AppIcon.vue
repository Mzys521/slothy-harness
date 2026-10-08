<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 18 })
const paths: Record<string, string[]> = {
  plus: ['M12 5v14', 'M5 12h14'],
  arrow: ['M12 19V5', 'm6 11 6-6 6 6'],
  panel: ['M9 3v18', 'M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1'],
  home: ['m3 10 9-7 9 7', 'M5 9v12h5v-7h4v7h5V9'],
  tool: ['M14 6a5 5 0 0 0-6 6L3 17a3 3 0 0 0 4 4l5-5a5 5 0 0 0 6-6l-3 3-4-4 3-3z'],
  memory: [
    'M8 4h8a4 4 0 0 1 4 4v8a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4V8a4 4 0 0 1 4-4',
    'M9 9h6v6H9z',
    'M8 1v3m8-3v3M8 20v3m8-3v3M1 8h3m-3 8h3m16-8h3m-3 8h3',
  ],
  sparkles: ['m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z', 'M20 2v4m-2-2h4'],
  folder: ['M3 6h6l2 2h10v12H3z'],
  search: ['m16 16 5 5'],
  message: ['M4 4h16v12H9l-5 4z'],
  logs: ['M5 3h14v18H5z', 'M8 7h8m-8 4h8m-8 4h5'],
  clock: ['M12 8v5l3 2'],
  chevron: ['m9 5 7 7-7 7'],
  down: ['m6 9 6 6 6-6'],
  close: ['m6 6 12 12', 'M18 6 6 18'],
  check: ['m5 12 4 4L19 6'],
  play: ['m8 4 12 8-12 8z'],
  pause: ['M8 5v14', 'M16 5v14'],
  stop: ['M6 6h12v12H6z'],
  refresh: ['M20 7v5h-5', 'M4 17v-5h5', 'M20 12a8 8 0 0 0-14-5', 'M4 12a8 8 0 0 0 14 5'],
  code: ['m8 7-5 5 5 5', 'm16 7 5 5-5 5', 'm14 4-4 16'],
  shield: ['m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z', 'm8 12 3 3 5-6'],
  warning: ['m12 3 10 18H2z', 'M12 9v5m0 3v1'],
  settings: ['m12 3 2 3 3-1 2 3-1 3 1 3-2 3-3-1-2 3-2-3-3 1-2-3 1-3-1-3 2-3 3 1z'],
  sun: ['M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5'],
  moon: ['M20.5 13A9 9 0 0 1 11 3.5 9 9 0 1 0 20.5 13z'],
  monitor: ['M3 4h18v13H3z', 'M12 17v4m-4 0h8'],
  download: ['M12 3v12', 'm7 10 5 5 5-5', 'M4 16v5h16v-5'],
  copy: ['M8 8h13v13H8z', 'M16 8V3H3v13h5'],
  link: [
    'm10 13 4-4',
    'M8 16l-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0',
    'M16 8l1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0',
  ],
  more: ['M4 12h.01', 'M12 12h.01', 'M20 12h.01'],
  pin: ['m14 3 7 7-4 1-4 6-6-6-6 6-4z', 'm3 21 6-6'],
  compose: ['M21 13v7H4V3h7', 'm12 12 9-9-3-3-9 9-1 4z'],
  'folder-plus': ['M3 6h6l2 2h10v12H3z', 'M12 11v6m-3-3h6'],
  repository: ['M5 3v9h14V5', 'M12 12v9', 'm16 7 3-3 3 3'],
  edit: ['m3 17 3 4L21 6l-4-3z', 'm14 6 4 4'],
}
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.65"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path v-for="(path, index) in paths[name] || paths.home" :key="index" :d="path" />
    <circle v-if="name === 'search'" cx="10.5" cy="10.5" r="6.5" />
    <circle v-if="name === 'clock'" cx="12" cy="12" r="9" />
    <circle v-if="name === 'settings'" cx="12" cy="12" r="3" />
    <circle v-if="name === 'sun'" cx="12" cy="12" r="4" />
  </svg>
</template>
