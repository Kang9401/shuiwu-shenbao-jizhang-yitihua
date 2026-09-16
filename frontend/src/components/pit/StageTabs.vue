<template>
  <el-radio-group :model-value="modelValue" size="large" @update:model-value="emit('update:modelValue', $event)">
    <el-radio-button value="pre_payment">缴款前（14 张表）</el-radio-button>
    <el-radio-button value="post_payment">缴款后（4 张表）</el-radio-button>
  </el-radio-group>
</template>

<script setup lang="ts">
import type { PaymentStage } from '../../features/pit/contracts'
defineProps<{ modelValue: PaymentStage }>()
const emit = defineEmits<{ 'update:modelValue': [value: PaymentStage] }>()
</script>
