                    elif text.startswith(('/add ', '/추가 ')):
                        parts = text.split(maxsplit=2)   # 최대 3개로 나눔

                        # 케이스 1: /add 이름 코드  (신규 종목 추가)
                        if len(parts) >= 3:
                            name = parts[1].strip()
                            code = parts[2].strip()

                            # 코드가 6자리 숫자인지 간단히 검사
                            if code.isdigit() and len(code) == 6:
                                stocks[name] = code
                                save_data({"stocks": stocks, "targets": targets})
                                send_telegram(f"✅ {name} ({code}) 추가 완료!")
                            else:
                                send_telegram("❌ 종목코드는 6자리 숫자여야 합니다.\n예: /add 모나미 005360")
                        
                        # 케이스 2: /add 이름  (기존 종목 중에서 찾기)
                        else:
                            name = parts[1].strip()
                            matched, code = find_ticker_by_name(name)
                            if code:
                                stocks[matched] = code
                                save_data({"stocks": stocks, "targets": targets})
                                send_telegram(f"✅ {matched} 추가 완료!")
                            else:
                                send_telegram(f"❌ '{name}'을(를) 찾을 수 없습니다.\n"
                                              f"신규 종목은 이렇게 추가하세요:\n"
                                              f"/add 모나미 005360")
