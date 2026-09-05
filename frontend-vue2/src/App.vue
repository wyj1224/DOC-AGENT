<template>
  <AdminWorkspace v-if="view === 'admin'" @close="openWorkspace" />
  <Workspace v-else @open-admin="openAdmin" />
</template>

<script>
import AdminWorkspace from "./components/AdminWorkspace.vue";
import Workspace from "./components/Workspace.vue";

export default {
  name: "App",
  components: { AdminWorkspace, Workspace },
  data() {
    return { view: window.location.hash === "#/admin" ? "admin" : "workspace" };
  },
  created() {
    window.addEventListener("hashchange", this.syncView);
  },
  beforeDestroy() {
    window.removeEventListener("hashchange", this.syncView);
  },
  methods: {
    syncView() {
      this.view = window.location.hash === "#/admin" ? "admin" : "workspace";
    },
    openAdmin() {
      window.location.hash = "#/admin";
    },
    openWorkspace() {
      window.location.hash = "#/workspace";
    },
  },
};
</script>
