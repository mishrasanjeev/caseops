import { nativeAssociationResponse } from '@/lib/native-association.server';
export const dynamic = 'force-dynamic';
export function GET(): Response {
  return nativeAssociationResponse('assetlinks');
}
