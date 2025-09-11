import axios from 'axios'

const API_BASE = (import.meta as any).env?.VITE_API_BASE || ''

const api = axios.create({
  baseURL: API_BASE || undefined,
  // You can add headers or timeout here if needed
})

export default api
