import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { api } from '@/lib/api/client'
import { paginated, toQuery } from '@/lib/api/pagination'

export const notificationSchema = z.object({
  id: z.string(), type: z.string(), title: z.string(), body: z.string(), link: z.string(),
  data: z.record(z.string(), z.unknown()), is_read: z.boolean(), read_at: z.string().nullable(), created_at: z.string(),
})
export type AppNotification = z.infer<typeof notificationSchema>

const preferenceSchema = z.object({ type: z.string(), label: z.string(), channel: z.string(), enabled: z.boolean() })
export type Preference = z.infer<typeof preferenceSchema>

const countSchema = z.object({ unread: z.number() })

export function useNotifications(f: { unread?: boolean; page?: number; page_size?: number } = {}) {
  return useQuery({
    queryKey: ['notifications', 'list', f],
    queryFn: () => api.get(`/notifications/${toQuery({ ...f, unread: f.unread ? 1 : undefined })}`, { schema: paginated(notificationSchema) }),
    placeholderData: keepPreviousData,
  })
}

export const useUnreadCount = (enabled = true) =>
  useQuery({
    queryKey: ['notifications', 'unread'],
    queryFn: () => api.get('/notifications/unread-count/', { schema: countSchema }),
    enabled,
    // The event stream invalidates this on every change; polling is a slow safety net for dropped sockets.
    refetchInterval: 5 * 60_000,
  })

export function useMarkRead() {
  const qc = useQueryClient()
  const done = () => void qc.invalidateQueries({ queryKey: ['notifications'] })
  return {
    one: useMutation({ mutationFn: (id: string) => api.post(`/notifications/${id}/read/`, undefined, { schema: notificationSchema }), onSuccess: done }),
    all: useMutation({ mutationFn: () => api.post('/notifications/read-all/', {}, { schema: countSchema }), onSuccess: done }),
  }
}

export const usePreferences = () =>
  useQuery({ queryKey: ['notifications', 'preferences'], queryFn: () => api.get('/notifications/preferences/', { schema: z.array(preferenceSchema) }) })

export function useSavePreferences() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (items: Pick<Preference, 'type' | 'channel' | 'enabled'>[]) =>
      api.put('/notifications/preferences/', items, { schema: z.array(preferenceSchema) }),
    onSuccess: (data) => qc.setQueryData(['notifications', 'preferences'], data),
  })
}

const channelSchema = z.object({ channel: z.string(), ready: z.boolean(), help: z.string(), detail: z.string() })
export type ChannelStatus = z.infer<typeof channelSchema>
export const useChannels = () =>
  useQuery({ queryKey: ['notifications', 'channels'], queryFn: () => api.get('/notifications/channels/', { schema: z.array(channelSchema) }) })

export function useTelegram() {
  const qc = useQueryClient()
  const refresh = () => void qc.invalidateQueries({ queryKey: ['notifications', 'channels'] })
  return {
    link: useMutation({ mutationFn: () => api.post('/notifications/telegram/link/', {}, { schema: z.object({ url: z.string() }) }) }),
    check: useMutation({ mutationFn: () => api.post('/notifications/telegram/check/', {}, { schema: z.object({ linked: z.boolean() }) }), onSuccess: refresh }),
    unlink: useMutation({ mutationFn: () => api.delete('/notifications/telegram/link/'), onSuccess: refresh }),
  }
}
