import type {ModelTriple} from './draft';
export type ReviewPreview = Partial<Record<'standards'|'spec',{
 selected:ModelTriple|null;selected_index:number|null;
 outcome:'different'|'no_different_family'|'unrecognized'|'none_runnable';
 unrecognized:ModelTriple[];
}>>;
