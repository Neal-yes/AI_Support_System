import { createRouter, createWebHistory } from 'vue-router'

const Home = () => import('../views/Home.vue')
const Tools = () => import('../views/Tools.vue')
const DB = () => import('../views/DB.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: Home },
    { path: '/tools', component: Tools },
    { path: '/db', component: DB }
  ]
})

export default router
