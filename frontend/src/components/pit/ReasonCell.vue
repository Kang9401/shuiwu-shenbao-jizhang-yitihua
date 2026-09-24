<template>
  <el-tooltip :content="reasonBody" :disabled="!reasonBody" placement="top" :show-after="300">
    <button type="button" class="reason-cell" :class="{ 'reason-cell--empty': !reasonBody }" @click="emit('open')">
      <span v-if="reasonBody" class="reason-cell__body">{{ reasonBody }}</span>
      <span v-else class="reason-cell__empty">填写原因</span>
    </button>
  </el-tooltip>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { displayReason } from '../../features/pit/reasonDisplay'

const props = defineProps<{ reason?: unknown }>()
const emit = defineEmits<{ open: [] }>()

const reasonBody = computed(() => displayReason(props.reason))
</script>

<style scoped>
.reason-cell { display:block; width:100%; padding:2px 0; border:0; background:transparent; color:inherit; text-align:left; cursor:pointer; }
.reason-cell__body { display:-webkit-box; overflow:hidden; max-height:3.1em; white-space:pre-line; line-height:1.55; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
.reason-cell--empty { color:var(--el-color-primary); }
.reason-cell__empty { line-height:1.55; }
</style>
