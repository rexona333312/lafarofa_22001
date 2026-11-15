"""Explicit music-only breaks; narration indices always refer to the original transcript."""
import math
import wave


def validate_music_insert(chunk):
    if not isinstance(chunk,dict):
        raise ValueError('Сцена должна быть объектом')
    if 'music_insert' not in chunk:
        return
    value=chunk['music_insert']
    duration=chunk.get('duration')
    if (value is not True or chunk.get('type')!='video' or chunk.get('template') or chunk.get('panels')
            or isinstance(duration,bool) or not isinstance(duration,(int,float))
            or not math.isfinite(duration) or not 1-1e-6<=duration<=5+1e-6):
        raise ValueError('music_insert: отдельное video без шаблона, duration от 1 до 5 секунд')
    if abs(duration*30-round(duration*30))>1e-6:
        raise ValueError('music_insert.duration должен соответствовать целому числу кадров 30 fps')


def inserted_duration(chunks):
    for chunk in chunks:
        validate_music_insert(chunk)
    if sum(c.get('music_insert') is True for c in chunks)>32:
        raise ValueError('Не больше 32 музыкальных вставок')
    return sum(c['duration'] for c in chunks if c.get('music_insert'))


def bind_music_words(chunks,words,audio_duration):
    inserted_duration(chunks)
    cursor,offset,result=0,0.,[]
    def at(i):return 0 if i==0 else audio_duration if i==len(words) else words[i]['start']
    for chunk in chunks:
        span=chunk.get('word_range')
        if (not isinstance(span,list) or len(span)!=2 or any(type(v) is not int for v in span)
                or span[0]!=cursor):
            raise ValueError('word_range: непрерывные диапазоны исходных слов')
        if chunk.get('music_insert'):
            if span[1]!=cursor:
                raise ValueError('Музыкальная вставка не содержит слов: word_range:[i,i]')
            start=at(cursor)+offset;end=start+chunk['duration'];offset+=chunk['duration']
            result.append({**chunk,'start':start,'end':end,'text':''})
        else:
            if not cursor<span[1]<=len(words):
                raise ValueError('word_range: диапазон должен содержать слова озвучки')
            end=span[1]
            result.append({**chunk,'start':at(cursor)+offset,'end':at(end)+offset,
                           'text':' '.join(w['word'] for w in words[cursor:end])})
            cursor=end
    if cursor!=len(words):
        raise ValueError('word_range не покрывает конец озвучки')
    return result


def shifted_words(words,chunks):
    result=[dict(w) for w in words]
    for c in chunks:
        if c.get('music_insert'):
            continue
        a,b=c['word_range'];offset=c['start']-(0 if a==0 else words[a]['start'])
        for i in range(a,b):
            result[i].update(start=words[i]['start']+offset,end=words[i]['end']+offset)
    return result


def pause_narration(source,destination,inserts):
    """Copy decoded PCM samples exactly, adding silence at original speech boundaries."""
    with wave.open(str(source),'rb') as src, wave.open(str(destination),'wb') as dst:
        dst.setparams(src.getparams());rate=src.getframerate()
        frame_bytes=src.getnchannels()*src.getsampwidth();cursor=0;offset=0.
        def copy(count):
            while count:
                block=src.readframes(min(count,48000))
                if not block:break
                dst.writeframesraw(block);count-=len(block)//frame_bytes
        for c in inserts:
            original=c['start']-offset;boundary=round(original*rate)
            if boundary<cursor or boundary>src.getnframes()+rate//20:
                raise ValueError('Музыкальная пауза выходит за пределы исходной озвучки')
            boundary=min(boundary,src.getnframes());copy(boundary-cursor);cursor=boundary
            remaining=round(c['duration']*rate)
            while remaining:
                n=min(remaining,48000);dst.writeframesraw(bytes(n*frame_bytes));remaining-=n
            offset+=c['duration']
        copy(src.getnframes()-cursor)
