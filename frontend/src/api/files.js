/**
 * File management API — content, download, uploads.
 */

import { authRequest, downloadBlob, readError } from './client'

export async function fetchSessionFilesGrouped(sessionId) {
  const res = await authRequest(`/sessions/${sessionId}/files/grouped`)
  if (!res.ok) throw new Error(await readError(res, 'Could not load files'))
  return res.json()
}

export async function fetchFileContent(relPath) {
  const res = await authRequest(`/files/content/${relPath}`)
  if (!res.ok) throw new Error(await readError(res, `Could not read file: ${res.status}`))
  return res.json()
}

export async function downloadFile(relPath, fileName) {
  return downloadBlob(`/files/download/${relPath}`, fileName)
}

export async function uploadFiles(sessionId, files) {
  const formData = new FormData()
  for (const file of files) formData.append('files', file)
  const res = await authRequest(`/sessions/${sessionId}/upload`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) throw new Error(await readError(res, 'Upload failed'))
  return res.json()
}

export async function createSessionAndUpload(files) {
  const formData = new FormData()
  for (const file of files) formData.append('files', file)
  const res = await authRequest('/sessions/create-and-upload', {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) throw new Error(await readError(res, 'Upload failed'))
  return res.json()
}
