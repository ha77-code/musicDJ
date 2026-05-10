// 听歌足迹 - 年度听歌足迹
const createOption = require('../util/option.js')
module.exports = (query, request) => {
  const data = {}
  if (query.year) {
    data.year = query.year
  }
  return request(
    `/api/content/activity/listen/data/year/report`,
    data,
    createOption(query),
  )
}
