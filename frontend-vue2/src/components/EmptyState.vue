<template>
  <div class="result-empty"><SearchX :size="23" /><strong>{{ title }}</strong><span>{{ text }}</span></div>
</template>

<script>
import { SearchX } from "lucide-vue";

export default {
  name: "EmptyState",
  components: { SearchX },
  props: { title: { type: String, default: "" }, text: { type: String, default: "" } },
};
</script>
