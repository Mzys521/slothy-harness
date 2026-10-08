import { createApp } from 'vue'
import App from './App.vue'
import { initializeAppearance } from './stores/appearance'
import './styles/theme.css'
import './styles/workspace.css'
import './styles/sidebar.css'
import './styles/models.css'

initializeAppearance()
createApp(App).mount('#app')
