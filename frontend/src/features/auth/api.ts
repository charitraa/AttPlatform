import { z } from 'zod'
import { api } from '@/lib/api/client'

const orgRef = z.object({ id: z.string(), name: z.string(), slug: z.string() })
const roleRef = z.object({ code: z.string(), name: z.string() })

export const meSchema = z.object({
  id: z.string(),
  email: z.string(),
  first_name: z.string(),
  last_name: z.string(),
  full_name: z.string(),
  phone: z.string(),
  timezone: z.string(),
  date_joined: z.string(),
  last_login: z.string().nullable(),
  organization: orgRef,
  role: roleRef,
  permissions: z.array(z.string()),
  memberships: z.array(z.object({ organization: orgRef, role: roleRef })),
})
export type Me = z.infer<typeof meSchema>

const sessionSchema = z.object({ access: z.string(), user: meSchema })
const accessSchema = z.object({ access: z.string() })
const detailSchema = z.object({ detail: z.string() })
export const invitationPreviewSchema = z.object({
  organization_name: z.string(),
  email: z.string(),
  role_name: z.string(),
  existing_account: z.boolean(),
})
export type InvitationPreview = z.infer<typeof invitationPreviewSchema>
export type Session = z.infer<typeof sessionSchema>

// Auth endpoints never trigger the client's automatic refresh-and-retry.
const noRefresh = { skipAuthRefresh: true }

export const authApi = {
  login: (email: string, password: string) =>
    api.post('/auth/login/', { email, password }, { schema: sessionSchema, ...noRefresh }),
  refresh: () => api.post('/auth/refresh/', undefined, { schema: accessSchema, ...noRefresh }),
  logout: () => api.post('/auth/logout/', undefined, noRefresh),
  forgotPassword: (email: string) => api.post('/auth/password/forgot/', { email }, { schema: detailSchema, ...noRefresh }),
  resetPassword: (data: { uid: string; token: string; new_password: string }) =>
    api.post('/auth/password/reset/', data, { schema: detailSchema, ...noRefresh }),
  previewInvitation: (token: string) =>
    api.post('/auth/invitations/preview/', { token }, { schema: invitationPreviewSchema, ...noRefresh }),
  acceptInvitation: (data: { token: string; password: string; first_name?: string; last_name?: string }) =>
    api.post('/auth/invitations/accept/', data, { schema: sessionSchema, ...noRefresh }),
  me: () => api.get('/me/', { schema: meSchema }),
  updateMe: (data: Partial<Pick<Me, 'first_name' | 'last_name' | 'phone' | 'timezone'>>) =>
    api.patch('/me/', data, { schema: meSchema }),
  changePassword: (data: { current_password: string; new_password: string }) =>
    api.post('/me/password/', data, { schema: accessSchema }),
}
