import { authPortalDetails } from './adapters/auth-portal.mjs';

export async function openLocalApp(id, options = {}) {
  if (id === 'auth-portal') {
    const details = authPortalDetails({ env: options.env });
    if (!details.configured) throw new Error('웹 로그인 전달 포털 주소가 구성되지 않았습니다.');
    return { ok: true, id, started: false, url: details.url };
  }
  const error = new Error('허용되지 않은 로컬 앱입니다.');
  error.code = 'app_not_allowed';
  error.status = 404;
  throw error;
}
