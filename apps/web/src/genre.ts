import type { Genre } from '@mozhou/contracts'

export const genreLabels: Record<Genre, string> = {
  historical_rebirth: '历史重生',
  urban_rebirth: '都市重生',
  eastern_fantasy: '东方玄幻',
  western_fantasy: '西方奇幻',
}

export const genreOptions = (Object.entries(genreLabels) as Array<[Genre, string]>).map(
  ([value, label]) => ({ value, label }),
)

export const genreDefaults: Record<Genre, {
  storyYear: number
  storyLocation: string
  titlePlaceholder: string
}> = {
  historical_rebirth: {
    storyYear: 1937,
    storyLocation: '福建南平',
    titlePlaceholder: '例如：烽火归途',
  },
  urban_rebirth: {
    storyYear: 1998,
    storyLocation: '福建南平',
    titlePlaceholder: '例如：回到九八年的南平',
  },
  eastern_fantasy: {
    storyYear: 728,
    storyLocation: '九州·云泽',
    titlePlaceholder: '例如：万山问道',
  },
  western_fantasy: {
    storyYear: 1243,
    storyLocation: '阿尔登大陆·北境',
    titlePlaceholder: '例如：灰塔之誓',
  },
}

export function isRebirthGenre(genre: Genre): boolean {
  return genre === 'historical_rebirth' || genre === 'urban_rebirth'
}

export function getStoryAnchorLabels(genre: Genre) {
  return isRebirthGenre(genre)
    ? {
        year: '重生年份',
        location: '重生地点',
        anchor: '重生锚点',
        divergence: '重生分歧点',
      }
    : {
        year: '故事纪年',
        location: '起始地域',
        anchor: '世界锚点',
        divergence: '故事引爆点',
      }
}
